import hashlib
import json
import os
import re
import shutil
from datetime import timedelta
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import select

from app.db.exports import Export
from app.db.library import now
from app.domain.uploads import asset_path
from app.exports import csv, vcard, xlsx
from app.exports.schema import Selection


def safe_part(value, fallback="Unidentified"):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", str(value)).strip(" .")[:70]
    if not name or name.split(".")[0].upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        name = fallback
    return name


def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def build(db, export, settings):
    selection = Selection.model_validate(export.selection)
    export.state, export.error = "building", None
    db.commit()
    folder = asset_path(settings.exports_dir, str(export.id))
    folder.mkdir(mode=0o700, exist_ok=True)
    estimated = export.counts["original_bytes"] if export.format == "zip" else 0
    if shutil.disk_usage(folder).free < estimated + 100 * 1024**2:
        raise RuntimeError("The exports drive needs more free space for this package.")
    tables = {
        table: [dict(row) for row in rows] for table, rows in export.snapshot["tables"].items()
    }
    target = folder / f"export.{export.format}"
    temporary = folder / f".building.{export.format}"
    if export.format == "xlsx":
        xlsx.write(temporary, tables, selection.fields, info=selection.info_sheet)
    elif export.format == "csv":
        table = selection.tables[0]
        csv.write(
            temporary,
            table,
            tables[table],
            selection.fields[table],
            bom=selection.csv_bom,
            spreadsheet_safe=selection.csv_safe,
        )
    elif export.format == "vcf":
        vcard.write(temporary, tables["contacts"], selection.fields["contacts"])
    else:
        make_zip(temporary, export, tables, selection, settings, folder)
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    temporary.replace(target)
    export.path, export.state, export.expires_at = (
        str(target.relative_to(settings.exports_dir)),
        "ready",
        now() + timedelta(days=settings.export_ttl_days),
    )
    db.commit()


def make_zip(target, export, tables, selection, settings, folder):
    manifest = {
        "format_version": 1,
        "export_id": str(export.id),
        "created_at": export.created_at.isoformat(),
        "fields": {table: selection.fields[table] for table in selection.tables},
        "counts": export.counts,
        "files": [],
        "row_mappings": [],
        "text_cleaning": "Whitespace formatting only; words are unchanged. Source text is always included for brochures.",
        "originals_are_not_redacted": True,
    }
    doc_paths, archive_files, seen_assets = {}, [], {}
    for source in export.snapshot["sources"]:
        company = f"Company-{(source['company_id'] or 'Unidentified')[:8]}"
        base = f"Expo-{source['expo_id'][:8]}/{company}/{safe_part(source['type'])}s/{source['document_id'][:8]}"
        refs = []
        for page in source["pages"]:
            asset_id = page["asset_id"]
            if asset_id not in seen_assets:
                filename = (
                    f"original-{asset_id[:8]}.{safe_part(page['extension'])}"
                    if page["mime"] == "application/pdf"
                    else f"page-{page['page_number']:03}-{safe_part(page['role'])}-{asset_id[:8]}.{safe_part(page['extension'])}"
                )
                seen_assets[asset_id] = f"{base}/{filename}"
                original = asset_path(settings.assets_dir, page["storage_path"])
                if not original.is_file() or digest_file(original) != page["sha256"]:
                    raise RuntimeError(
                        "An original file is unavailable or its checksum does not match. Check the originals drive."
                    )
                archive_files.append((original, seen_assets[asset_id]))
            relative = seen_assets[asset_id]
            refs.append(relative)
            manifest["files"].append(
                {
                    key: page[key]
                    for key in (
                        "page_id",
                        "asset_id",
                        "sha256",
                        "page_number",
                        "pdf_page_no",
                        "role",
                    )
                }
                | {
                    "document_id": source["document_id"],
                    "expo_id": source["expo_id"],
                    "company_id": source["company_id"],
                    "path": relative,
                }
            )
        doc_paths[source["document_id"]] = list(dict.fromkeys(refs))
        if source["type"] == "brochure":
            text = "\n\n".join(
                f"--- Page {page['page_number']} ---\n{page['text']}" for page in source["pages"]
            )
            manifest.setdefault("brochure_text", []).append(
                {
                    "document_id": source["document_id"],
                    "source_path": f"{base}/text-source.txt",
                    "cleaned_path": f"{base}/text-cleaned.txt" if source["ai_finished"] else None,
                    "missing_reason": None
                    if source["ai_finished"]
                    else "AI extraction has not finished. Full source text is included.",
                }
            )
    for table, rows in tables.items():
        for number, row in enumerate(rows, 2):
            ids = row.get("_document_ids", [])
            if "files" in selection.fields[table]:
                row["files"] = "\n".join(
                    dict.fromkeys(path for id in ids for path in doc_paths.get(id, []))
                )
            manifest["row_mappings"].append(
                {
                    "table": table,
                    "row": number,
                    "record_id": row.get("_entity_id"),
                    "document_ids": ids,
                    "values": {field: row.get(field, "") for field in selection.fields[table]},
                }
            )
    spreadsheet = folder / "export.xlsx"
    xlsx.write(spreadsheet, tables, selection.fields, info=selection.info_sheet)
    with ZipFile(
        target, "w", compression=ZIP_DEFLATED, compresslevel=1, allowZip64=True
    ) as archive:
        archive.write(spreadsheet, "tables/export.xlsx")
        if selection.include_csv:
            for table, rows in tables.items():
                path = folder / f"{table}.csv"
                csv.write(
                    path,
                    table,
                    rows,
                    selection.fields[table],
                    bom=selection.csv_bom,
                    spreadsheet_safe=selection.csv_safe,
                )
                archive.write(path, f"tables/{table}.csv")
                path.unlink()
        if selection.include_vcard and "contacts" in tables:
            path = folder / "contacts.vcf"
            vcard.write(path, tables["contacts"], selection.fields["contacts"])
            archive.write(path, "tables/contacts.vcf")
            path.unlink()
        for original, relative in archive_files:
            archive.write(original, relative)
        for source, reference in zip(
            (row for row in export.snapshot["sources"] if row["type"] == "brochure"),
            manifest.get("brochure_text", []),
            strict=True,
        ):
            text = "\n\n".join(
                f"--- Page {page['page_number']} ---\n{page['text']}" for page in source["pages"]
            )
            archive.writestr(reference["source_path"], text)
            if reference["cleaned_path"]:
                archive.writestr(
                    reference["cleaned_path"],
                    "\n\n".join(" ".join(paragraph.split()) for paragraph in text.split("\n\n")),
                )
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr(
            "README.txt",
            "Expo Buddy private export\n\nOpen tables/export.xlsx or the selected CSV/vCard files. All paths are relative; each original is stored once, with page mappings in manifest.json. SHA-256 checksums describe the untouched original.\n\nSelected fields: "
            + json.dumps(manifest["fields"])
            + "\nCounts: "
            + json.dumps(export.counts)
            + "\n\nPersonal notes are included only when selected. Original photos, PDFs and brochure source text still contain printed information: deselecting fields is not redaction.\nMulti-values use labelled values separated by |. CSV spreadsheet-safe mode "
            + (
                "is enabled: formula-like strings are prefixed with an apostrophe; app values are unchanged."
                if selection.csv_safe
                else "is disabled by your selection."
            )
            + "\n\nCleaned text uses whitespace formatting only; words are unchanged. Source transcripts retain page markers.\n",
        )
    spreadsheet.unlink()


def expire(db, settings):
    for row in db.scalars(select(Export).where(Export.state == "ready", Export.expires_at < now())):
        path = asset_path(settings.exports_dir, row.path)
        if path.parent == settings.exports_dir / str(row.id):
            shutil.rmtree(path.parent, ignore_errors=True)
        row.state = "expired"
        row.path = ""
    db.commit()
