from collections import defaultdict
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.db.exports import Export
from app.db.intelligence import Appearance, Company, Contact
from app.db.library import Asset, Document, DocumentPage, Expo, Note
from app.db.processing import ExtractionRun, OCRResult
from app.domain.capture import notes_for_document
from app.domain.contact_values import channel_issue
from app.domain.jobs import enqueue
from app.domain.review import document_status, pending, region_hint, warning
from app.domain.tags import document_labels
from app.exports.schema import Selection


def values(channels, kind):
    return " | ".join(
        dict.fromkeys(
            f"{row.get('label', '') + ': ' if row.get('label') else ''}{row['raw']}"
            for row in channels
            if row.get("kind") == kind
        )
    )


def freeze(db, selection: Selection, settings, active_expo=None, *, include_notes=True):
    if not include_notes and any(
        "notes" in selection.fields.get(table, []) for table in selection.tables
    ):
        raise HTTPException(403, "This token needs the notes scope to export personal notes.")
    statement = select(Document).where(Document.deleted_at.is_(None))
    if selection.scope == "active":
        active_expo = selection.expo_ids[0] if selection.expo_ids else active_expo
        if not active_expo:
            raise HTTPException(422, "Choose an active expo or select All expos.")
        statement = statement.where(Document.expo_id == active_expo)
    elif selection.scope == "expos":
        statement = statement.where(Document.expo_id.in_(selection.expo_ids))
    elif selection.scope == "selected":
        from sqlalchemy import or_

        statement = statement.where(
            or_(
                Document.id.in_(selection.document_ids),
                Document.company_id.in_(selection.company_ids),
            )
        )
    elif selection.scope == "search":
        from app.domain.hybrid import hybrid_search

        hits = hybrid_search(
            db,
            settings,
            selection.query,
            expo_id=selection.expo_ids[0] if selection.expo_ids else active_expo,
            include_notes=include_notes,
            **{
                k: v
                for k, v in selection.filters.items()
                if k in ("type", "review_state", "company_id", "tag", "category", "processed_by", "include_related")
            },
        )["results"]
        statement = statement.where(
            Document.id.in_([UUID(row["document_id"]) for row in hits if row.get("document_id")])
        )
    docs = list(db.scalars(statement.order_by(Document.expo_id, Document.created_at).limit(20001)))
    if len(docs) > 20000:
        raise HTTPException(
            422, "Choose a smaller scope: an export can contain up to 20,000 documents."
        )
    proposals, region = pending(db), region_hint(db)
    doc_warnings = {doc.id: warning(db, doc, proposals) for doc in docs}
    companies, per_company, rows, sources = (
        {},
        defaultdict(list),
        {table: [] for table in selection.tables},
        [],
    )
    notes_selected = include_notes and any(
        "notes" in selection.fields.get(table, []) for table in selection.tables
    )
    expo_names = {row.id: row.name for row in db.scalars(select(Expo))}
    doc_notes = {doc.id: notes_for_document(db, doc) for doc in docs} if notes_selected else {}
    all_doc_pages = {}
    for doc in docs:
        pages = list(
            db.scalars(
                select(DocumentPage)
                .where(DocumentPage.document_id == doc.id)
                .order_by(DocumentPage.order)
            )
        )
        all_doc_pages[doc.id] = pages
        if doc.company_id:
            company = db.get(Company, doc.company_id)
            if company and not company.deleted_at:
                companies[company.id] = company
                per_company[(company.id, doc.expo_id)].append(doc)
        common = {
            "id": str(doc.id),
            "expo": expo_names[doc.expo_id],
            "company_name": companies[doc.company_id].display_name
            if doc.company_id in companies
            else "",
            "title": doc.title,
            "type": doc.type,
            "processing_state": doc.processing_state,
            "review_state": document_status(db, doc, proposals)["review_status"],
            "review_warning": doc_warnings[doc.id],
            "tags": " | ".join(document_labels(db, doc)),
            "notes": "\n".join(note.text for note in doc_notes.get(doc.id, [])),
            "files": "\n".join(
                f"{settings.canonical_origin}/documents/{doc.id}?page={page.id}" for page in pages
            ),
        }
        if "documents" in rows:
            rows["documents"].append(
                {field: common.get(field, "") for field in selection.fields["documents"]}
                | {
                    "review_warning": doc_warnings[doc.id],
                    "_entity_id": str(doc.id),
                    "_document_ids": [str(doc.id)],
                }
            )
        ordered = []
        for page in pages:
            asset = db.get(Asset, page.asset_id)
            ocr = db.scalar(
                select(OCRResult)
                .where(OCRResult.document_page_id == page.id)
                .order_by(OCRResult.revision.desc())
                .limit(1)
            )
            ordered.append(
                {
                    "page_id": str(page.id),
                    "asset_id": str(asset.id),
                    "storage_path": asset.storage_path,
                    "sha256": asset.sha256,
                    "bytes": asset.bytes,
                    "mime": asset.mime,
                    "extension": asset.storage_path.rsplit(".", 1)[-1],
                    "page_number": page.order + 1,
                    "pdf_page_no": page.pdf_page_no,
                    "role": page.role,
                    "text": ocr.text if ocr else "",
                }
            )
        sources.append(
            {
                "document_id": str(doc.id),
                "expo_id": str(doc.expo_id),
                "company_id": str(doc.company_id) if doc.company_id else None,
                "type": doc.type,
                "pages": ordered,
                "ai_finished": bool(
                    db.scalar(
                        select(ExtractionRun.id)
                        .where(
                            ExtractionRun.document_id == doc.id,
                            ExtractionRun.stage == "ai",
                            ExtractionRun.status == "succeeded",
                        )
                        .limit(1)
                    )
                ),
            }
        )
    brochure_only = 0
    for (company_id, expo_id), related in per_company.items():
        company = companies[company_id]
        notes = {note.id: note.text for doc in related for note in doc_notes.get(doc.id, [])}
        if notes_selected:
            notes.update(
                {
                    note.id: note.text
                    for note in db.scalars(
                        select(Note).where(Note.company_id == company_id, Note.deleted_at.is_(None))
                    )
                }
            )
        company_documents = list(
            db.scalars(
                select(Document).where(
                    Document.company_id == company_id, Document.deleted_at.is_(None)
                )
            )
        )
        review_warnings = list(
            dict.fromkeys(
                message for doc in company_documents if (message := warning(db, doc, proposals))
            )
        )
        if any(channel_issue(channel, region) for channel in company.channels):
            review_warnings.append("Invalid company contact syntax")
        base = {
            "review_warning": "; ".join(review_warnings),
            "id": str(company.id),
            "expo": expo_names[expo_id],
            "company_name": company.display_name,
            "products": " | ".join(company.products),
            "services": " | ".join(company.services),
            "categories": " | ".join(company.categories),
            "business_role": company.business_role,
            "description": company.description,
            "notes": "\n".join(notes.values()),
            "tags": " | ".join(
                dict.fromkeys(label for doc in related for label in document_labels(db, doc))
            ),
            "files": "\n".join(
                f"{settings.canonical_origin}/documents/{doc.id}" for doc in related
            ),
            "websites": " | ".join(
                filter(None, [company.website, values(company.channels, "web")])
            ),
        }
        for field, channel in (("phones", "phone"), ("emails", "email"), ("addresses", "address")):
            base[field] = values(company.channels, channel)
        if "companies" in rows:
            rows["companies"].append(
                {field: base.get(field, "") for field in selection.fields["companies"]}
                | {
                    "review_warning": base["review_warning"],
                    "_entity_id": str(company.id),
                    "_document_ids": [str(doc.id) for doc in related],
                }
            )
        contacts = list(
            db.scalars(
                select(Contact)
                .where(Contact.company_id == company_id, Contact.deleted_at.is_(None))
                .order_by(Contact.full_name)
            )
        )
        relevant = []
        for person in contacts:
            appearances = list(
                db.scalars(select(Appearance.expo_id).where(Appearance.contact_id == person.id))
            )
            if appearances and expo_id not in appearances:
                continue
            relevant.append(person)
            if "contacts" in rows:
                contact = {
                    **base,
                    "id": str(person.id),
                    "full_name": person.full_name,
                    "designation": person.designation,
                    "department": person.department,
                }
                for field, channel in (
                    ("phones", "phone"),
                    ("emails", "email"),
                    ("websites", "web"),
                    ("addresses", "address"),
                ):
                    contact[field] = values(person.channels, channel) or base.get(field, "")
                contact_warnings = list(review_warnings)
                if person.source_document_id:
                    source_doc = db.get(Document, person.source_document_id)
                    if source_doc:
                        contact_warnings += [warning(db, source_doc, proposals)]
                if any(channel_issue(channel, region) for channel in person.channels):
                    contact_warnings.append("Invalid contact syntax")
                contact["review_warning"] = "; ".join(
                    dict.fromkeys(item for item in contact_warnings if item)
                )
                result = {field: contact.get(field, "") for field in selection.fields["contacts"]}
                result["review_warning"] = contact["review_warning"]
                # Labelled channel data is internal to the snapshot; never put deselected channels in the manifest.
                result["_entity_id"] = str(person.id)
                result["_document_ids"] = [str(doc.id) for doc in related]
                channels = person.channels + [
                    row
                    for row in company.channels
                    if row.get("kind") not in {item.get("kind") for item in person.channels}
                ]
                if company.website and not any(item.get("kind") == "web" for item in channels):
                    channels += [{"kind": "web", "label": "Company", "raw": company.website}]
                result["_vcard_channels"] = [
                    row
                    for row in channels
                    if {
                        "phone": "phones",
                        "email": "emails",
                        "web": "websites",
                        "address": "addresses",
                    }.get(row.get("kind"))
                    in selection.fields["contacts"]
                ]
                rows["contacts"].append(result)
        if not relevant:
            brochure_only += 1
    flagged = 0
    for table, data in rows.items():
        flagged += sum(bool(row.get("review_warning")) for row in data)
        if (
            any(row.get("review_warning") for row in data)
            and "review_warning" not in selection.fields[table]
        ):
            selection.fields[table] = [*selection.fields[table], "review_warning"]
    counts = {table: len(data) for table, data in rows.items()}
    counts["flagged_rows"] = flagged
    counts.update(
        documents_in_scope=len(docs),
        brochure_only_companies=brochure_only,
        original_bytes=sum(
            {
                page["asset_id"]: page["bytes"] for source in sources for page in source["pages"]
            }.values()
        ),
    )
    return {
        "tables": rows,
        "sources": sources,
        "created_scope": selection.model_dump(mode="json"),
        "counts": counts,
    }


def create(db, selection, settings, active_expo=None, *, token_id=None, include_notes=True):
    snapshot = freeze(db, selection, settings, active_expo, include_notes=include_notes)
    if snapshot["counts"]["flagged_rows"] and not selection.allow_unreviewed:
        raise HTTPException(
            409,
            "This export contains unreviewed or flagged data. Review it first, or explicitly allow unreviewed data after checking the preview warnings.",
        )
    row = Export(
        format=selection.format,
        selection=selection.model_dump(mode="json"),
        snapshot=snapshot,
        counts=snapshot["counts"],
        token_id=token_id,
    )
    db.add(row)
    db.flush()
    enqueue(db, "export", row.id, 1)
    return row
