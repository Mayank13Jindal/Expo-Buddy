from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.intelligence import Tag, TagLink
from app.domain.fields import entity


def assign(db: Session, kind: str, id: UUID, labels: list[str], *, actor: str = "owner"):
    owner = entity(db, kind, id)
    result = []
    for label in dict.fromkeys(label.strip() for label in labels):
        if not label or len(label) > 100:
            raise HTTPException(422, "Use tags with 1–100 characters.")
        tag = db.scalar(select(Tag).where(func.lower(Tag.label) == label.lower()))
        if not tag:
            tag = Tag(label=label, source=actor)
            db.add(tag)
            db.flush()
        if not db.scalar(
            select(TagLink.id).where(
                TagLink.tag_id == tag.id, TagLink.entity_type == kind, TagLink.entity_id == id
            )
        ):
            db.add(TagLink(tag_id=tag.id, entity_type=kind, entity_id=id))
        result.append(tag)
    db.flush()
    from app.db.library import Document

    if kind == "document":
        index_tags(db, owner)
    elif kind == "company":
        for doc in db.scalars(
            select(Document).where(Document.company_id == id, Document.deleted_at.is_(None))
        ):
            index_tags(db, doc)
    return result


def document_labels(db, document):
    from sqlalchemy import and_, or_

    from app.domain.capture import groups_for_document

    return list(
        db.scalars(
            select(Tag.label)
            .join(TagLink)
            .where(
                or_(
                    and_(TagLink.entity_type == "document", TagLink.entity_id == document.id),
                    and_(
                        TagLink.entity_type == "company", TagLink.entity_id == document.company_id
                    ),
                    and_(
                        TagLink.entity_type == "capture_group",
                        TagLink.entity_id.in_(groups_for_document(db, document.id)),
                    ),
                    and_(TagLink.entity_type == "expo", TagLink.entity_id == document.expo_id),
                )
            )
            .distinct()
        )
    )


def index_tags(db, document):
    from app.pipeline.index import index_text

    index_text(
        db,
        "tag",
        document.id,
        "; ".join(document_labels(db, document)),
        document.revision,
        document=document,
    )
