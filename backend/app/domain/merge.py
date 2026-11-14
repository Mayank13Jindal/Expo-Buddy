from uuid import UUID

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.intelligence import Appearance, Contact, DuplicateSuggestion, EditHistory
from app.db.library import Document, now
from app.domain.fields import FIELDS, entity, set_field


def merge(db: Session, kind: str, source_id: UUID, target_id: UUID, values: dict) -> EditHistory:
    if kind not in ("company", "contact") or source_id == target_id:
        raise HTTPException(422, "Choose two different companies or contacts.")
    source, target = entity(db, kind, source_id), entity(db, kind, target_id)
    if source.deleted_at or target.deleted_at:
        raise HTTPException(409, "Restore these records before merging them.")
    before = {
        "source_id": str(source_id),
        "source": {key: getattr(source, key) for key in FIELDS[kind]},
        "target": {key: getattr(target, key) for key in FIELDS[kind]},
        "references": [],
        "removed_appearances": [],
    }
    references = (
        ((Contact, "company_id"), (Document, "company_id"), (Appearance, "company_id"))
        if kind == "company"
        else ((Appearance, "contact_id"),)
    )
    for model, field in references:
        for row in db.scalars(select(model).where(getattr(model, field) == source_id)):
            before["references"].append(
                {"table": model.__tablename__, "id": str(row.id), "field": field}
            )
            if model is Appearance and kind == "contact":
                duplicate = db.scalar(
                    select(Appearance.id).where(
                        Appearance.document_id == row.document_id,
                        Appearance.company_id == row.company_id,
                        Appearance.contact_id == target_id,
                    )
                )
                if duplicate:
                    before["removed_appearances"].append(
                        {
                            "id": str(row.id),
                            "document_id": str(row.document_id),
                            "company_id": str(row.company_id),
                            "contact_id": str(source_id),
                            "expo_id": str(row.expo_id),
                        }
                    )
                    db.delete(row)
                    continue
            setattr(row, field, target_id)
    for key, value in values.items():
        set_field(db, kind, target_id, key, value)
    for duplicate in db.scalars(
        select(DuplicateSuggestion).where(
            DuplicateSuggestion.source_id.in_([source_id, target_id]),
            DuplicateSuggestion.candidate_id.in_([source_id, target_id]),
        )
    ):
        duplicate.state = "merged"
    source.deleted_at = now()
    history = EditHistory(
        entity_type=kind,
        entity_id=target_id,
        field="__merge__",
        old=jsonable_encoder(before),
        new=jsonable_encoder({key: getattr(target, key) for key in FIELDS[kind]}),
    )
    db.add(history)
    db.flush()
    return history


def undo_merge(db: Session, history: EditHistory):
    if history.undone_at:
        return
    target = entity(db, history.entity_type, history.entity_id)
    if any(getattr(target, key) != value for key, value in history.new.items()):
        raise HTTPException(
            409, "The merged record changed again. Compare its history before editing."
        )
    source = entity(db, history.entity_type, UUID(history.old["source_id"]))
    models = {model.__tablename__: model for model in (Contact, Document, Appearance)}
    for reference in history.old["references"]:
        row = db.get(models[reference["table"]], UUID(reference["id"]))
        if row:
            if getattr(row, reference["field"]) != target.id:
                raise HTTPException(409, "A linked record changed after this merge.")
            setattr(row, reference["field"], source.id)
    for removed in history.old["removed_appearances"]:
        db.add(Appearance(**{key: UUID(value) for key, value in removed.items()}))
    source.deleted_at = None
    for key, value in history.old["target"].items():
        set_field(db, history.entity_type, target.id, key, value)
    history.undone_at = now()
    db.flush()
