from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.intelligence import Company, Contact, EditHistory, FieldValue, Proposal
from app.db.library import Document, now
from app.pipeline.index import index_text

MODELS = {"company": Company, "contact": Contact, "document": Document}
FIELDS = {
    "company": {
        "display_name",
        "aliases",
        "website",
        "description",
        "business_role",
        "products",
        "services",
        "categories",
        "channels",
    },
    "contact": {"full_name", "designation", "department", "channels"},
    "document": {"title", "type"},
}


def entity(db: Session, kind: str, id: UUID):
    model = MODELS.get(kind)
    row = db.get(model, id) if model else None
    if row is None:
        raise HTTPException(404, "This record was not found.")
    return row


def validate_value(kind, field, value):
    if field == "channels":
        if (
            not isinstance(value, list)
            or len(value) > 200
            or any(
                not isinstance(item, dict)
                or item.get("kind") not in ("phone", "email", "web", "address")
                or not isinstance(item.get("raw"), str)
                for item in value
            )
        ):
            raise HTTPException(422, "Enter valid contact details.")
    elif field in ("products", "services", "categories", "aliases"):
        if not isinstance(value, list) or not all(
            isinstance(item, str) and len(item) <= 5000 for item in value
        ):
            raise HTTPException(422, "Enter a list of text values.")
    elif not isinstance(value, str) or len(value) > {
        "display_name": 300,
        "full_name": 300,
        "designation": 300,
        "department": 300,
        "business_role": 300,
        "title": 400,
        "website": 2000,
    }.get(field, 20000):
        raise HTTPException(422, "Enter a text value.")


def proposal(
    db: Session,
    kind: str,
    id: UUID,
    field: str,
    value,
    *,
    reason: str,
    evidence: list | None = None,
    document_id: UUID | None = None,
    actor: str = "ai",
) -> Proposal | None:
    row = entity(db, kind, id)
    if field not in FIELDS[kind]:
        raise HTTPException(422, "This field cannot be changed.")
    validate_value(kind, field, value)
    from app.domain.review import changes, region_hint

    if not changes(field, getattr(row, field), value, region_hint(db)):
        return None
    for existing in db.scalars(
        select(Proposal).where(
            Proposal.entity_type == kind,
            Proposal.entity_id == id,
            Proposal.field == field,
            Proposal.state == "pending",
        )
    ):
        if existing.proposed_value == value:
            return existing
    result = Proposal(
        entity_type=kind,
        entity_id=id,
        field=field,
        current_value=getattr(row, field),
        proposed_value=value,
        reason=reason,
        evidence=evidence or [],
        document_id=document_id,
        actor=actor,
    )
    db.add(result)
    if document_id:
        documents = [db.get(Document, document_id)]
    elif kind == "document":
        documents = [row]
    elif kind == "contact":
        documents = [db.get(Document, row.source_document_id)] if row.source_document_id else []
    else:
        documents = list(
            db.scalars(
                select(Document).where(Document.company_id == id, Document.deleted_at.is_(None))
            )
        )
    for document in documents:
        if document:
            document.review_state = "needs_attention"
    db.flush()
    return result


def set_field(
    db: Session,
    kind: str,
    id: UUID,
    field: str,
    value,
    *,
    source: str = "user",
    evidence: list | None = None,
    run_id: UUID | None = None,
    document_id: UUID | None = None,
    actor: str = "owner",
    generated: bool = False,
) -> bool:
    row = entity(db, kind, id)
    if field not in FIELDS[kind]:
        raise HTTPException(422, "This field cannot be changed.")
    validate_value(kind, field, value)
    previous = db.scalar(
        select(FieldValue)
        .where(
            FieldValue.entity_type == kind,
            FieldValue.entity_id == id,
            FieldValue.field == field,
            FieldValue.is_current.is_(True),
        )
        .with_for_update()
    )
    old = getattr(row, field)
    if (
        source != "user"
        and previous
        and previous.value != value
        and (previous.source == "user" or (old and not generated))
    ):
        proposal(
            db,
            kind,
            id,
            field,
            value,
            reason="Your correction is kept."
            if previous.source == "user"
            else "A source gives a different value.",
            evidence=evidence,
            document_id=document_id,
        )
        return False
    if previous and previous.source == "user" and source != "user":
        return True
    if previous:
        previous.is_current = False
    setattr(row, field, value)
    db.add(
        FieldValue(
            entity_type=kind,
            entity_id=id,
            field=field,
            value=value,
            source=source,
            evidence=evidence or [],
            extraction_run_id=run_id,
        )
    )
    if old != value:
        db.add(
            EditHistory(
                entity_type=kind, entity_id=id, field=field, old=old, new=value, actor=actor
            )
        )
    if field == "channels":
        sync_channels(db, kind, id, value, source)
    db.flush()
    index_entity(db, kind, row, document_id)
    return True


def index_entity(db: Session, kind: str, row, document_id: UUID | None = None):
    text = "\n".join(
        "; ".join(item.get("raw", "") if isinstance(item, dict) else item for item in value)
        if isinstance(value, list)
        else value
        for key in FIELDS[kind]
        if isinstance((value := getattr(row, key)), (str, list))
    )
    doc = db.get(Document, document_id) if document_id else (row if kind == "document" else None)
    index_text(
        db,
        "field",
        row.id,
        text,
        doc.revision if doc else 1,
        document=doc,
        company_id=row.id if kind == "company" else getattr(row, "company_id", None),
    )


def undo_edit(db: Session, history: EditHistory):
    if history.undone_at:
        return
    current = entity(db, history.entity_type, history.entity_id)
    if getattr(current, history.field) != history.new:
        raise HTTPException(409, "This field has changed again. Review its history before editing.")
    set_field(db, history.entity_type, history.entity_id, history.field, history.old)
    history.undone_at = now()


def sync_channels(db, kind, id, values, source):
    from app.db.intelligence import ContactChannel
    from app.domain.contact_values import normalise_channel

    existing = list(
        db.scalars(
            select(ContactChannel).where(
                ContactChannel.owner_type == kind, ContactChannel.owner_id == id
            )
        )
    )
    keys = {(item["kind"], item["raw"]) for item in values}
    for row in existing:
        if (row.kind, row.raw) not in keys:
            row.deleted_at = now()
    for item in values:
        row = next(
            (row for row in existing if row.kind == item["kind"] and row.raw == item["raw"]), None
        )
        if not row:
            row = ContactChannel(
                owner_type=kind,
                owner_id=id,
                kind=item["kind"],
                raw=item["raw"],
                normalised=normalise_channel(item["kind"], item["raw"]),
                source=source,
            )
            db.add(row)
        row.label = item.get("label", "")
        row.evidence = item.get("evidence", {})
        row.deleted_at = None
