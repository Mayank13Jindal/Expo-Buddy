import csv
import hashlib
import io
import json
from datetime import timedelta
from uuid import UUID
from zipfile import ZipFile

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app.db.exports import Export
from app.db.library import now
from app.exports.package import build, expire
from tests.test_library import expo, upload


def fake_records(web):
    expo_id = expo(web)
    _, card = upload(web, expo_id)
    company = web.post(
        "/api/v1/companies",
        json={
            "fields": {
                "display_name": "FICTIONAL Solar Company",
                "products": ["Fictional mounting structures"],
            }
        },
    ).json()
    web.post(
        f"/api/v1/documents/{card['document']['id']}/attach-company",
        json={"company_id": company["id"]},
    )
    for name in ("=SUM(1)", "Fictional " + "अ" * 80):
        web.post(
            "/api/v1/contacts",
            json={
                "company_id": company["id"],
                "fields": {
                    "full_name": name,
                    "channels": [
                        {"kind": "phone", "label": "Mobile", "raw": "+910000000001"},
                        {"kind": "phone", "label": "Office", "raw": "00123000456"},
                        {"kind": "email", "label": "Work", "raw": "example@example.invalid"},
                    ],
                },
            },
        )
    web.post(
        "/api/v1/notes",
        json={"document_id": card["document"]["id"], "text": "FICTIONAL PRIVATE ORCHID NOTE"},
    )
    # A second brochure-only company using a separate appearance; same original stays shared.
    _, brochure = upload(web, expo_id)
    other = web.post(
        "/api/v1/companies", json={"fields": {"display_name": "FICTIONAL Brochure Only"}}
    ).json()
    web.post(
        f"/api/v1/documents/{brochure['document']['id']}/attach-company",
        json={"company_id": other["id"]},
    )
    return expo_id, card, company


def generate(web, engine, settings, body):
    response = web.post("/api/v1/exports", json={**body, "allow_unreviewed": True})
    assert response.status_code == 202, response.text
    with Session(engine) as db:
        row = db.get(Export, UUID(response.json()["id"]))
        build(db, row, settings)
        db.commit()
    download = web.get(f"/api/v1/exports/{response.json()['id']}/download")
    assert download.status_code == 200
    return response.json()["id"], download.content


def test_xlsx_csv_field_order_text_and_frozen_snapshot(signed_in, engine, settings):
    _, _, company = fake_records(signed_in)
    fields = ["phones", "full_name", "company_name"]
    body = {
        "scope": "all",
        "format": "xlsx",
        "tables": ["contacts"],
        "fields": {"contacts": fields},
    }
    preview = signed_in.post(
        "/api/v1/exports/preview", json={**body, "allow_unreviewed": True}
    ).json()
    assert preview["counts"]["contacts"] == 2
    assert preview["counts"]["brochure_only_companies"] == 1
    response = signed_in.post("/api/v1/exports", json={**body, "allow_unreviewed": True}).json()
    signed_in.patch(
        f"/api/v1/companies/{company['id']}",
        json={"fields": {"display_name": "Changed after snapshot"}},
    )
    with Session(engine) as db:
        build(db, db.get(Export, UUID(response["id"])), settings)
    workbook = load_workbook(
        io.BytesIO(signed_in.get(f"/api/v1/exports/{response['id']}/download").content)
    )
    sheet = workbook["Contacts"]
    assert [cell.value for cell in sheet[1]] == ["Phones", "Person", "Company", "Review warning"]
    assert sheet["A2"].value.startswith("Mobile: +91") and "00123000456" in sheet["A2"].value
    assert sheet["B2"].value == "=SUM(1)" and sheet["B2"].data_type == "s"
    assert sheet["C2"].value == "FICTIONAL Solar Company"
    _, raw = generate(signed_in, engine, settings, {**body, "format": "csv"})
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    assert rows[1][1] == "'=SUM(1)"
    assert rows[0] == ["Phones", "Person", "Company", "Review warning"]


def test_zip_manifest_original_hash_order_notes_and_expiry(signed_in, engine, settings):
    _, card, _ = fake_records(signed_in)
    fields = {
        "contacts": ["full_name", "phones"],
        "companies": ["company_name"],
        "documents": ["title", "files"],
    }
    id, content = generate(
        signed_in,
        engine,
        settings,
        {
            "scope": "all",
            "format": "zip",
            "tables": list(fields),
            "fields": fields,
            "include_vcard": True,
        },
    )
    with ZipFile(io.BytesIO(content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert "FICTIONAL PRIVATE ORCHID NOTE" not in archive.read("manifest.json").decode()
        assert all("notes" not in row["values"] for row in manifest["row_mappings"])
        assert (
            "tables/export.xlsx" in archive.namelist()
            and "tables/contacts.vcf" in archive.namelist()
        )
        for item in manifest["files"]:
            assert hashlib.sha256(archive.read(item["path"])).hexdigest() == item["sha256"]
            assert item["page_number"] == 1
            assert not item["path"].startswith("/") and ".." not in item["path"]
        assert b"not redaction" in archive.read("README.txt")
    with Session(engine) as db:
        row = db.get(Export, UUID(id))
        row.expires_at = now() - timedelta(days=1)
        db.commit()
        expire(db, settings)
    assert signed_in.get(f"/api/v1/exports/{id}/download").status_code == 410
    assert signed_in.get(f"/api/v1/assets/{card['asset']['id']}/original").status_code == 200


def test_vcard_escaping_multiple_labels_and_utf8_folding(signed_in, engine, settings):
    fake_records(signed_in)
    _, content = generate(
        signed_in,
        engine,
        settings,
        {
            "scope": "all",
            "format": "vcf",
            "tables": ["contacts"],
            "fields": {"contacts": ["full_name", "company_name", "phones", "emails", "notes"]},
        },
    )
    lines = content.split(b"\r\n")
    assert max(map(len, lines)) <= 75
    unfolded = content.decode().replace("\r\n ", "")
    assert unfolded.count("BEGIN:VCARD") == 2 and unfolded.count(".TEL;") == 4
    assert "Office" in unfolded and "+910000000001" in unfolded and "00123000456" in unfolded
    assert "NOTE:FICTIONAL PRIVATE ORCHID NOTE" in unfolded
    assert "\nVERSION:3.0" in unfolded


def test_brochure_zip_keeps_full_text_and_pdf_page_mapping(signed_in, engine, settings):
    from reportlab.pdfgen.canvas import Canvas

    from app.db.library import Document
    from app.pipeline.ocr import read_document
    from app.pipeline.prepare import prepare_document

    buffer = io.BytesIO()
    canvas = Canvas(buffer)
    for number in range(1, 4):
        canvas.drawString(
            20,
            760,
            f"FICTIONAL BROCHURE PAGE {number} makes solar mounting structures, example only.",
        )
        canvas.showPage()
    canvas.save()
    _, source = upload(signed_in, expo(signed_in), buffer.getvalue())
    id = source["document"]["id"]
    signed_in.patch(f"/api/v1/documents/{id}", json={"type": "brochure"})
    with Session(engine) as db:
        doc = db.get(Document, UUID(id))
        prepare_document(db, doc, settings)
        read_document(db, doc, settings)
        db.commit()
    _, content = generate(
        signed_in,
        engine,
        settings,
        {
            "scope": "all",
            "format": "zip",
            "tables": ["documents"],
            "fields": {"documents": ["title"]},
        },
    )
    with ZipFile(io.BytesIO(content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        pages = manifest["files"]
        assert [page["pdf_page_no"] for page in pages] == [1, 2, 3]
        assert len({page["path"] for page in pages}) == 1
        text = archive.read(manifest["brochure_text"][0]["source_path"]).decode()
        assert "BROCHURE PAGE 3" in text
        assert manifest["brochure_text"][0]["cleaned_path"] is None


def test_expiry_survives_an_export_folder_deleted_by_hand(engine, settings):
    with Session(engine) as db:
        row = Export(format="csv", selection={}, snapshot={}, counts={}, state="ready")
        db.add(row)
        db.flush()
        row.path = f"{row.id}/export.csv"  # Folder was never created, as if removed by hand.
        row.expires_at = now() - timedelta(days=1)
        db.commit()
        expire(db, settings)
        assert row.state == "expired"
