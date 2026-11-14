from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.dependencies import DB, OwnerSession
from app.api.library import find, record
from app.db.intelligence import (
    Appearance,
    Company,
    Contact,
    DuplicateSuggestion,
    EditHistory,
    FieldValue,
    Proposal,
    Tag,
    TagLink,
)
from app.db.library import Document, Note
from app.db.processing import ExtractionRun
from app.domain import fields, merge, tags
from app.pipeline.ai import appearance

router = APIRouter(prefix="/api/v1", tags=["records"])


@router.post("/duplicates/{id}/dismiss")
def dismiss_duplicate(id: UUID, session: OwnerSession, db: DB):
    row = find(db, DuplicateSuggestion, id)
    row.state = "dismissed"
    db.commit()
    return {"saved": True}


def company_detail(db: DB, id: UUID, *, include_notes: bool = True):
    company = find(db, Company, id)
    appearances = list(db.scalars(select(Appearance).where(Appearance.company_id == id)))
    docs = list(
        db.scalars(
            select(Document).where(
                Document.id.in_([row.document_id for row in appearances]),
                Document.deleted_at.is_(None),
            )
        )
    )
    contacts = list(
        db.scalars(select(Contact).where(Contact.company_id == id, Contact.deleted_at.is_(None)))
    )
    from app.domain import review as review_values

    proposals = review_values.pending(db)
    result = {
        **record(company),
        "contacts": [
            {**record(row), **review_values.contact_status(db, row, proposals)} for row in contacts
        ],
        "appearances": [record(row) for row in appearances],
        "review_warning": "Source needs review — verify these contact details."
        if any(
            review_values.document_status(db, doc, proposals)["review_status"] != "reviewed"
            for doc in docs
        )
        else "",
        "documents": [
            {**record(row), **review_values.document_status(db, row, proposals)} for row in docs
        ],
        "field_sources": [
            record(row)
            for row in db.scalars(
                select(FieldValue).where(
                    FieldValue.entity_type == "company",
                    FieldValue.entity_id == id,
                    FieldValue.is_current.is_(True),
                )
            )
        ],
        "tags": [
            record(row)
            for row in db.scalars(
                select(Tag)
                .join(TagLink)
                .where(TagLink.entity_type == "company", TagLink.entity_id == id)
            )
        ],
    }
    result["processed_by"] = [
        {
            "provider": run.provider,
            "cloud": bool(run.output.get("cloud") or run.provider in ("openrouter", "chatgpt")),
        }
        for run in db.scalars(
            select(ExtractionRun).where(
                ExtractionRun.document_id.in_([doc.id for doc in docs]),
                ExtractionRun.stage == "ai",
                ExtractionRun.status == "succeeded",
            )
        )
    ]
    if include_notes:
        from app.domain.capture import notes_for_document

        combined = {
            row.id: row
            for row in db.scalars(
                select(Note).where(Note.company_id == id, Note.deleted_at.is_(None))
            )
        }
        for doc in docs:
            combined.update({row.id: row for row in notes_for_document(db, doc)})
        result["notes"] = [record(row) for row in combined.values()]
    return result


@router.get("/companies")
def companies(session: OwnerSession, db: DB, expo_id: UUID | None = None):
    statement = select(Company).where(Company.deleted_at.is_(None))
    if expo_id:
        statement = statement.where(
            Company.id.in_(select(Appearance.company_id).where(Appearance.expo_id == expo_id))
        )
    return [
        {
            **record(row),
            "people": [
                person.full_name
                for person in db.scalars(
                    select(Contact).where(
                        Contact.company_id == row.id, Contact.deleted_at.is_(None)
                    )
                )
            ],
        }
        for row in db.scalars(statement.order_by(Company.display_name).limit(1000))
    ]


@router.get("/companies/{id}")
def company(id: UUID, session: OwnerSession, db: DB):
    return company_detail(db, id)


class Changes(BaseModel):
    fields: dict[str, Any] = Field(max_length=20)


@router.post("/companies", status_code=201)
def create_company(body: Changes, session: OwnerSession, db: DB):
    row = Company()
    db.add(row)
    db.flush()
    for key, value in body.fields.items():
        fields.set_field(db, "company", row.id, key, value)
    db.commit()
    return record(row)


@router.patch("/companies/{id}")
def edit_company(id: UUID, body: Changes, session: OwnerSession, db: DB):
    for key, value in body.fields.items():
        fields.set_field(db, "company", id, key, value)
    db.commit()
    return company_detail(db, id)


@router.get("/contacts")
def contacts(
    session: OwnerSession, db: DB, expo_id: UUID | None = None, company_id: UUID | None = None
):
    statement = select(Contact).where(Contact.deleted_at.is_(None))
    if expo_id:
        statement = statement.where(
            Contact.company_id.in_(
                select(Appearance.company_id).where(Appearance.expo_id == expo_id)
            )
        )
    if company_id:
        statement = statement.where(Contact.company_id == company_id)
    from app.domain.review import contact_status, pending

    proposals = pending(db)
    result = []
    for person in db.scalars(statement.order_by(Contact.full_name).limit(1000)):
        company = db.get(Company, person.company_id)
        if company and not company.deleted_at:
            result.append(
                {
                    **record(person),
                    "company_name": company.display_name,
                    **contact_status(db, person, proposals),
                }
            )
    return result


@router.get("/contacts/{id}")
def contact(id: UUID, session: OwnerSession, db: DB):
    row = find(db, Contact, id)
    return {
        **record(row),
        "company": record(find(db, Company, row.company_id)),
        "field_sources": [
            record(value)
            for value in db.scalars(
                select(FieldValue).where(
                    FieldValue.entity_type == "contact",
                    FieldValue.entity_id == id,
                    FieldValue.is_current.is_(True),
                )
            )
        ],
    }


class NewContact(Changes):
    company_id: UUID
    document_id: UUID | None = None


@router.post("/contacts", status_code=201)
def create_contact(body: NewContact, session: OwnerSession, db: DB):
    find(db, Company, body.company_id)
    row = Contact(company_id=body.company_id)
    db.add(row)
    db.flush()
    for key, value in body.fields.items():
        fields.set_field(db, "contact", row.id, key, value)
    if body.document_id:
        doc = find(db, Document, body.document_id)
        if doc.company_id != body.company_id:
            raise HTTPException(422, "Choose a source document from this company.")
        row.source_document_id = doc.id
        appearance(db, find(db, Company, body.company_id), doc, row)
    db.commit()
    return record(row)


@router.patch("/contacts/{id}")
def edit_contact(id: UUID, body: Changes, session: OwnerSession, db: DB):
    for key, value in body.fields.items():
        fields.set_field(db, "contact", id, key, value)
    db.commit()
    return record(find(db, Contact, id))


@router.get("/companies/{id}/history")
def company_history(id: UUID, session: OwnerSession, db: DB):
    return history(db, "company", id)


@router.get("/contacts/{id}/history")
def contact_history(id: UUID, session: OwnerSession, db: DB):
    return history(db, "contact", id)


def history(db, kind, id):
    return [
        record(row)
        for row in db.scalars(
            select(EditHistory)
            .where(EditHistory.entity_type == kind, EditHistory.entity_id == id)
            .order_by(EditHistory.created_at.desc())
            .limit(200)
        )
    ]


@router.post("/history/{id}/undo")
def undo_history(id: UUID, session: OwnerSession, db: DB):
    row = find(db, EditHistory, id)
    merge.undo_merge(db, row) if row.field == "__merge__" else fields.undo_edit(db, row)
    db.commit()
    return {"saved": True}


class MergeInput(BaseModel):
    entity_type: str = Field(pattern="^(company|contact)$")
    source_id: UUID
    target_id: UUID
    values: dict[str, Any] = Field(default_factory=dict, max_length=20)


@router.post("/merge/preview")
def merge_preview(body: MergeInput, session: OwnerSession, db: DB):
    return {
        "source": record(fields.entity(db, body.entity_type, body.source_id)),
        "target": record(fields.entity(db, body.entity_type, body.target_id)),
    }


@router.post("/merge")
def merge_records(body: MergeInput, session: OwnerSession, db: DB):
    row = merge.merge(db, body.entity_type, body.source_id, body.target_id, body.values)
    db.commit()
    return {"history_id": row.id, "target_id": body.target_id}


@router.get("/review")
def review(session: OwnerSession, db: DB, expo_id: UUID | None = None):
    statement = select(Document).where(Document.deleted_at.is_(None))
    if expo_id:
        statement = statement.where(Document.expo_id == expo_id)
    from app.domain import review as review_values

    proposals = review_values.pending(db, expo_id)
    return {
        "documents": [
            {**record(row), **review_values.document_status(db, row, proposals)}
            for row in db.scalars(statement.order_by(Document.created_at))
            if review_values.document_status(db, row, proposals)["review_status"]
            == "needs_attention"
        ][:500],
        "proposals": [review_values.proposal_view(db, row) for row in proposals[:500]],
        "duplicates": [
            record(row)
            for row in db.scalars(
                select(DuplicateSuggestion).where(DuplicateSuggestion.state == "pending").limit(200)
            )
        ],
    }


@router.post("/review/{id}/resolve")
def resolve_review(id: UUID, session: OwnerSession, db: DB):
    row = find(db, Document, id)
    from app.domain.review import for_document

    if for_document(db, row):
        raise HTTPException(
            409, "Decide the outstanding suggestions before marking this document reviewed."
        )
    row.review_state = "reviewed"
    row.review_reasons = []
    db.commit()
    return record(row)


class ProposalDecision(BaseModel):
    selected_changes: list[int] | None = Field(default=None, max_length=400)


@router.post("/proposals/{id}/{decision}")
def decide_proposal(
    id: UUID, decision: str, session: OwnerSession, db: DB, body: ProposalDecision | None = None
):
    row = db.scalar(
        select(Proposal)
        .where(Proposal.id == id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise HTTPException(404, "Suggestion not found.")
    if decision not in ("accept", "reject"):
        raise HTTPException(422, "Choose accept or reject.")
    if row.state != "pending":
        return record(row)
    if decision == "accept":
        current = fields.entity(db, row.entity_type, row.entity_id)
        db.refresh(current, with_for_update=True)
        if getattr(current, row.field) != row.current_value:
            raise HTTPException(
                409, "This field changed. Refresh the proposal before accepting it."
            )
        from app.domain.review import changes, key, proposal_view, region_hint

        region = region_hint(db)
        operations = changes(row.field, row.current_value, row.proposed_value, region)
        chosen = (
            body.selected_changes
            if body and body.selected_changes is not None
            else list(range(len(operations)))
        )
        view = proposal_view(db, row)
        if len(set(chosen)) != len(chosen) or any(
            index < 0 or index >= len(operations) for index in chosen
        ):
            raise HTTPException(422, "Choose valid individual changes.")
        if any(not view["changes"][index]["can_accept"] for index in chosen):
            raise HTTPException(
                422, "Correct invalid contact details against the source before accepting them."
            )
        value = (
            list(row.current_value) if isinstance(row.current_value, list) else row.current_value
        )
        for index in chosen:
            operation = operations[index]
            if operation["operation"] == "add":
                value.append(operation["value"])
            elif operation["operation"] == "remove":
                value = [
                    item
                    for item in value
                    if key(item, row.field, region) != key(operation["value"], row.field, region)
                ]
            else:
                value = operation["value"]
        fields.set_field(
            db, row.entity_type, row.entity_id, row.field, value, evidence=row.evidence
        )
    row.state = (
        ("partially_accepted" if len(chosen) < len(operations) else "accepted")
        if decision == "accept"
        else "rejected"
    )
    db.commit()
    return record(row)


class TagInput(BaseModel):
    entity_type: str = Field(pattern="^(company|contact|document)$")
    entity_id: UUID
    labels: list[str] = Field(max_length=100)


@router.get("/tags")
def list_tags(session: OwnerSession, db: DB):
    return [record(row) for row in db.scalars(select(Tag).order_by(Tag.label))]


@router.post("/tags/assign")
def assign_tags(body: TagInput, session: OwnerSession, db: DB):
    rows = tags.assign(db, body.entity_type, body.entity_id, body.labels)
    db.commit()
    return [record(row) for row in rows]


@router.get("/documents/{id}/extractions")
def extraction_history(id: UUID, session: OwnerSession, db: DB):
    find(db, Document, id)
    return [
        record(row)
        for row in db.scalars(
            select(ExtractionRun)
            .where(ExtractionRun.document_id == id)
            .order_by(ExtractionRun.created_at.desc())
        )
    ]


class AttachCompany(BaseModel):
    company_id: UUID


@router.post("/documents/{id}/attach-company")
def attach_company(id: UUID, body: AttachCompany, session: OwnerSession, db: DB):
    row = find(db, Document, id)
    company = find(db, Company, body.company_id)
    row.company_id = company.id
    appearance(db, company, row)
    db.commit()
    return record(row)
