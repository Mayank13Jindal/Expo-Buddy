from datetime import date
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.api.dependencies import DB, OwnerSession
from app.db.intelligence import Company
from app.db.library import Asset, Document, DocumentPage, Expo, Note, Preference, now
from app.domain.fields import set_field
from app.pipeline.index import index_note, index_text

router = APIRouter(prefix="/api/v1", tags=["library"])


def record(value) -> dict:
    return {column.key: getattr(value, column.key) for column in value.__table__.columns}


def find(db: DB, model, id: UUID):
    row = db.get(model, id)
    if not row:
        raise HTTPException(404, "This item was not found.")
    return row


class ExpoInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    venue: str = Field(default="", max_length=300)
    city: str = Field(default="", max_length=200)
    archived: bool = False
    client_uuid: UUID | None = None

    @model_validator(mode="after")
    def check_dates(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("Give the expo a name.")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("The end date must be after the start date.")
        return self


@router.get("/expos")
def list_expos(session: OwnerSession, db: DB):
    return [record(expo) for expo in db.scalars(select(Expo).order_by(Expo.created_at.desc()))]


@router.post("/expos", status_code=201)
def create_expo(body: ExpoInput, session: OwnerSession, db: DB):
    if body.client_uuid and (
        existing := db.scalar(select(Expo).where(Expo.client_uuid == body.client_uuid))
    ):
        return record(existing)
    expo = Expo(**body.model_dump())
    db.add(expo)
    db.flush()
    preference = db.scalar(
        select(Preference).where(Preference.owner_id == session.owner_id).with_for_update()
    )
    if preference.active_expo_id is None:
        preference.active_expo_id = expo.id
        preference.revision += 1
    db.commit()
    return record(expo)


@router.get("/expos/{id}")
def get_expo(id: UUID, session: OwnerSession, db: DB):
    return record(find(db, Expo, id))


@router.patch("/expos/{id}")
def update_expo(id: UUID, body: ExpoInput, session: OwnerSession, db: DB):
    expo = find(db, Expo, id)
    for key, value in body.model_dump(exclude_unset=True, exclude={"client_uuid"}).items():
        setattr(expo, key, value)
    db.commit()
    return record(expo)


class PreferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active_expo_id: UUID | None = None
    theme: str | None = Field(default=None, pattern="^(light|dark|system)$")
    region_hint: str | None = Field(default=None, max_length=8)
    default_search_scope: str | None = Field(default=None, pattern="^(active|all)$")
    expected_revision: int | None = None


@router.get("/preferences")
def get_preferences(session: OwnerSession, db: DB):
    return record(db.scalar(select(Preference).where(Preference.owner_id == session.owner_id)))


@router.patch("/preferences")
def update_preferences(body: PreferenceInput, session: OwnerSession, db: DB):
    preference = db.scalar(
        select(Preference).where(Preference.owner_id == session.owner_id).with_for_update()
    )
    if body.expected_revision is not None and preference.revision != body.expected_revision:
        raise HTTPException(
            409, "The active expo changed on another device. Reload and choose again."
        )
    if body.active_expo_id:
        find(db, Expo, body.active_expo_id)
    for key, value in body.model_dump(exclude_unset=True, exclude={"expected_revision"}).items():
        setattr(preference, key, value)
    preference.revision += 1
    db.commit()
    return record(preference)


@router.get("/documents")
def list_documents(
    session: OwnerSession,
    db: DB,
    expo_id: UUID | None = None,
    type: str | None = None,
    review_state: str | None = None,
    company_id: UUID | None = None,
    tag: str | None = None,
    category: str | None = None,
    processed_by: str | None = None,
    trash: bool = False,
    limit: int = 200,
    offset: int = 0,
):
    statement = select(Document).where(
        Document.deleted_at.is_not(None) if trash else Document.deleted_at.is_(None)
    )
    if expo_id:
        statement = statement.where(Document.expo_id == expo_id)
    if type:
        statement = statement.where(Document.type == type)
    if review_state:
        from app.domain.review import review_filter

        statement = statement.where(review_filter(db, review_state))
    from app.domain.search_filters import eligible_documents

    eligible = eligible_documents(
        db, company_id=company_id, tag=tag, category=category, processed_by=processed_by
    )
    if eligible is not None:
        statement = statement.where(Document.id.in_(eligible))
    docs = db.scalars(
        statement.order_by(Document.created_at.desc())
        .offset(max(0, offset))
        .limit(min(max(1, limit), 500))
    )
    from app.domain.review import document_status, pending

    proposals = pending(db)
    result = []
    for doc in docs:
        first = db.scalar(
            select(DocumentPage)
            .where(DocumentPage.document_id == doc.id)
            .order_by(DocumentPage.order)
        )
        result.append(
            {
                **record(doc),
                **document_status(db, doc, proposals),
                "thumbnail_asset_id": first.asset_id if first else None,
            }
        )
    return result


@router.get("/documents/{id}")
def get_document(id: UUID, session: OwnerSession, db: DB):
    doc = find(db, Document, id)
    pages = []
    for page in db.scalars(
        select(DocumentPage).where(DocumentPage.document_id == id).order_by(DocumentPage.order)
    ):
        from app.db.processing import AssetDerivative

        preview_revision = db.scalar(
            select(AssetDerivative.revision)
            .where(
                AssetDerivative.document_page_id == page.id,
                AssetDerivative.asset_id == page.asset_id,
                AssetDerivative.kind == "preview",
                AssetDerivative.revision <= doc.revision,
            )
            .order_by(AssetDerivative.revision.desc())
            .limit(1)
        )
        pages.append(
            {
                **record(page),
                "asset": record(find(db, Asset, page.asset_id)),
                "preview_revision": preview_revision,
            }
        )
    from app.domain.capture import notes_for_document

    notes = notes_for_document(db, doc)
    from app.domain.review import document_status

    return {
        **record(doc),
        **document_status(db, doc),
        "pages": pages,
        "notes": [record(note) for note in notes],
    }


class DocumentInput(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=400)
    type: str | None = Field(default=None, pattern="^(card|brochure|other)$")
    review_state: str | None = Field(
        default=None, pattern="^(unreviewed|needs_attention|reviewed)$"
    )


@router.patch("/documents/{id}")
def update_document(id: UUID, body: DocumentInput, session: OwnerSession, db: DB):
    doc = find(db, Document, id)
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            if key in ("title", "type"):
                set_field(db, "document", doc.id, key, value)
            else:
                if key == "review_state" and value == "reviewed":
                    from app.domain.review import for_document

                    if for_document(db, doc):
                        raise HTTPException(
                            409,
                            "Decide the outstanding suggestions before marking this document reviewed.",
                        )
                    doc.review_reasons = []
                setattr(doc, key, value)
    index_text(db, "field", doc.id, doc.title, doc.revision, document=doc)
    db.commit()
    return record(doc)


@router.delete("/documents/{id}")
def trash_document(id: UUID, session: OwnerSession, db: DB):
    doc = find(db, Document, id)
    doc.deleted_at = now()
    db.commit()
    return {"saved": True, "message": "Moved to Trash. Originals are kept."}


@router.post("/documents/{id}/restore")
def restore_document(id: UUID, session: OwnerSession, db: DB):
    doc = find(db, Document, id)
    if doc.processing_state in ("removing", "removed") or db.scalar(
        select(Asset.id)
        .join(DocumentPage)
        .where(DocumentPage.document_id == id, Asset.purged_at.is_not(None))
        .limit(1)
    ):
        from fastapi import HTTPException

        raise HTTPException(
            410,
            "The originals were permanently removed or removal is in progress. Recover from a backup or upload them again.",
        )
    doc.deleted_at = None
    db.commit()
    return record(doc)


class MoveExpo(BaseModel):
    expo_id: UUID


@router.post("/documents/{id}/move-expo")
def move_document(id: UUID, body: MoveExpo, session: OwnerSession, db: DB):
    find(db, Expo, body.expo_id)
    doc = find(db, Document, id)
    doc.expo_id = body.expo_id
    db.commit()
    return record(doc)


class NoteInput(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    document_id: UUID | None = None
    asset_id: UUID | None = None
    expo_id: UUID | None = None
    company_id: UUID | None = None
    capture_group_id: UUID | None = None
    client_uuid: UUID | None = None

    @model_validator(mode="after")
    def one_target(self):
        if (
            sum(
                value is not None
                for value in (
                    self.document_id,
                    self.asset_id,
                    self.expo_id,
                    self.company_id,
                    self.capture_group_id,
                )
            )
            != 1
        ):
            raise ValueError("Choose one place for the note.")
        return self


@router.post("/notes", status_code=201)
def create_note(body: NoteInput, session: OwnerSession, db: DB):
    if body.client_uuid and (
        existing := db.scalar(select(Note).where(Note.client_uuid == body.client_uuid))
    ):
        return record(existing)
    for key, model in (("document_id", Document), ("asset_id", Asset), ("expo_id", Expo)):
        if value := getattr(body, key):
            find(db, model, value)
    if body.company_id:
        find(db, Company, body.company_id)
    if body.capture_group_id:
        from app.db.capture import CaptureGroup

        find(db, CaptureGroup, body.capture_group_id)
    note = Note(**body.model_dump())
    db.add(note)
    db.flush()
    index_note(db, note)
    db.commit()
    return record(note)


@router.get("/notes")
def list_notes(session: OwnerSession, db: DB, expo_id: UUID | None = None):
    statement = select(Note).where(Note.deleted_at.is_(None))
    if expo_id:
        statement = statement.where(Note.expo_id == expo_id)
    return [
        record(note) for note in db.scalars(statement.order_by(Note.created_at.desc()).limit(500))
    ]


class NoteEdit(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


@router.patch("/notes/{id}")
def edit_note(id: UUID, body: NoteEdit, session: OwnerSession, db: DB):
    note = find(db, Note, id)
    note.text = body.text
    index_note(db, note)
    db.commit()
    return record(note)


@router.delete("/notes/{id}")
def delete_note(id: UUID, session: OwnerSession, db: DB):
    note = find(db, Note, id)
    note.deleted_at = now()
    index_note(db, note)
    db.commit()
    return {"saved": True}


@router.get("/dashboard")
def dashboard(request: Request, session: OwnerSession, db: DB, expo_id: UUID | None = None):
    from app.domain.dashboard import summary

    return summary(db, expo_id, settings=request.app.state.settings)
