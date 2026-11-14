from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, text

from app.db.capture import CaptureGroup, CaptureItem, SyncReceipt
from app.db.library import Document, DocumentPage, Expo, Note, now
from app.domain.tags import assign
from app.pipeline.index import index_note


def lock_uuid(db, id: UUID):
    if db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": int.from_bytes(id.bytes[:8], signed=True)},
        )


def target(db, kind, id):
    models = {"expo": Expo, "group": CaptureGroup, "file": CaptureItem}
    model = models.get(kind)
    row = db.get(model, id) if model else None
    if row is None:
        raise HTTPException(422, "Sync the expo, booth and photo before their notes.")
    if kind == "file":
        page = db.get(DocumentPage, row.document_page_id)
        return {"document_id": page.document_id}
    return {"expo_id" if kind == "expo" else "capture_group_id": row.id}


def save_note(
    db, *, client_uuid, revision, target_kind, target_id, text_value, deleted=False, origin="phone"
):
    lock_uuid(db, client_uuid)
    receipt = db.scalar(select(SyncReceipt).where(SyncReceipt.client_uuid == client_uuid))
    payload = {"target_kind": target_kind, "target_id": str(target_id)}
    if receipt and (receipt.kind != "note" or receipt.payload != payload):
        raise HTTPException(409, "This capture ID already belongs to a different item.")
    if receipt and receipt.revision >= revision:
        return db.get(Note, receipt.server_id)
    targets = target(db, target_kind, target_id)
    row = (
        db.get(Note, receipt.server_id)
        if receipt
        else Note(client_uuid=client_uuid, origin=origin, **targets)
    )
    row.text = text_value
    row.deleted_at = now() if deleted else None
    db.add(row)
    db.flush()
    index_note(db, row)
    if receipt:
        receipt.revision = revision
    else:
        db.add(
            SyncReceipt(
                client_uuid=client_uuid,
                kind="note",
                server_id=row.id,
                revision=revision,
                payload=payload,
            )
        )
    db.flush()
    return row


def save_tags(db, *, client_uuid, target_kind, target_id, labels, actor="phone"):
    lock_uuid(db, client_uuid)
    receipt = db.scalar(select(SyncReceipt).where(SyncReceipt.client_uuid == client_uuid))
    if receipt:
        if receipt.kind != "tags":
            raise HTTPException(409, "This capture ID already belongs to another item.")
        return receipt
    targets = target(db, target_kind, target_id)
    if "capture_group_id" in targets:
        from app.db.intelligence import Tag, TagLink

        # Booth tags follow its pages through later grouping.
        for label in labels:
            label = label.strip()
            if not label or len(label) > 100:
                raise HTTPException(422, "Use short tags.")
            tag = db.scalar(select(Tag).where(Tag.label == label))
            if not tag:
                tag = Tag(label=label, source=actor)
                db.add(tag)
                db.flush()
            if not db.scalar(
                select(TagLink.id).where(
                    TagLink.tag_id == tag.id,
                    TagLink.entity_type == "capture_group",
                    TagLink.entity_id == target_id,
                )
            ):
                db.add(TagLink(tag_id=tag.id, entity_type="capture_group", entity_id=target_id))
    elif "document_id" in targets:
        assign(db, "document", targets["document_id"], labels, actor=actor)
    else:
        # Expo tags are searchable without assigning them to unrelated companies.
        from app.db.intelligence import Tag, TagLink

        for label in labels:
            label = label.strip()
            if not label or len(label) > 100:
                raise HTTPException(422, "Use short tags.")
            tag = db.scalar(select(Tag).where(Tag.label == label))
            if not tag:
                tag = Tag(label=label, source=actor)
                db.add(tag)
                db.flush()
            if not db.scalar(
                select(TagLink.id).where(
                    TagLink.tag_id == tag.id,
                    TagLink.entity_type == "expo",
                    TagLink.entity_id == target_id,
                )
            ):
                db.add(TagLink(tag_id=tag.id, entity_type="expo", entity_id=target_id))
    receipt = SyncReceipt(client_uuid=client_uuid, kind="tags", server_id=target_id, payload={})
    db.add(receipt)
    db.flush()
    from app.domain.tags import index_tags

    for doc in db.scalars(
        select(Document).where(
            Document.expo_id
            == (db.get(CaptureGroup, target_id).expo_id if target_kind == "group" else target_id),
            Document.deleted_at.is_(None),
        )
    ):
        index_tags(db, doc)
    return receipt


def groups_for_document(db, id):
    return list(
        db.scalars(
            select(CaptureItem.capture_group_id)
            .join(DocumentPage, DocumentPage.id == CaptureItem.document_page_id)
            .where(DocumentPage.document_id == id, CaptureItem.capture_group_id.is_not(None))
            .distinct()
        )
    )


def notes_for_document(db, doc):
    from sqlalchemy import or_

    from app.db.processing import AssetDerivative

    asset_ids = list(
        db.scalars(select(DocumentPage.asset_id).where(DocumentPage.document_id == doc.id))
    )
    asset_ids += list(
        db.scalars(
            select(AssetDerivative.asset_id)
            .join(DocumentPage)
            .where(DocumentPage.document_id == doc.id, AssetDerivative.kind == "replacement")
        )
    )
    return list(
        db.scalars(
            select(Note).where(
                Note.deleted_at.is_(None),
                or_(
                    Note.document_id == doc.id,
                    Note.asset_id.in_(asset_ids),
                    Note.capture_group_id.in_(groups_for_document(db, doc.id)),
                ),
            )
        )
    )
