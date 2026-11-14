from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.intelligence import Company, Tag, TagLink
from app.db.library import Document
from app.db.processing import ExtractionRun


def eligible_documents(
    db: Session,
    *,
    company_id: UUID | None = None,
    tag: str | None = None,
    category: str | None = None,
    processed_by: str | None = None,
):
    if not any((company_id, tag, category, processed_by)):
        return None
    statement = select(Document.id).where(Document.deleted_at.is_(None))
    if company_id:
        statement = statement.where(Document.company_id == company_id)
    if tag:
        from app.db.capture import CaptureItem
        from app.db.library import DocumentPage

        tag_ids = select(Tag.id).where(func.lower(Tag.label) == tag.lower())
        statement = statement.where(
            or_(
                Document.id.in_(
                    select(TagLink.entity_id).where(
                        TagLink.entity_type == "document", TagLink.tag_id.in_(tag_ids)
                    )
                ),
                Document.id.in_(
                    select(DocumentPage.document_id)
                    .join(CaptureItem, CaptureItem.document_page_id == DocumentPage.id)
                    .where(
                        CaptureItem.capture_group_id.in_(
                            select(TagLink.entity_id).where(
                                TagLink.entity_type == "capture_group", TagLink.tag_id.in_(tag_ids)
                            )
                        )
                    )
                ),
                Document.company_id.in_(
                    select(TagLink.entity_id).where(
                        TagLink.entity_type == "company", TagLink.tag_id.in_(tag_ids)
                    )
                ),
            )
        )
    if category:
        ids = [
            row.id
            for row in db.scalars(select(Company).where(Company.deleted_at.is_(None)))
            if category.casefold() in [item.casefold() for item in row.categories]
        ]
        statement = statement.where(Document.company_id.in_(ids))
    if processed_by in ("local", "cloud"):
        cloud = or_(
            ExtractionRun.provider.in_(("chatgpt", "openrouter")),
            ExtractionRun.output["cloud"].as_boolean().is_(True),
        )
        statement = statement.where(
            Document.id.in_(
                select(ExtractionRun.document_id).where(
                    ExtractionRun.stage == "ai",
                    ExtractionRun.status == "succeeded",
                    cloud
                    if processed_by == "cloud"
                    else or_(
                        ExtractionRun.provider == "ollama",
                        ExtractionRun.output["cloud"].as_boolean().is_(False),
                    )
                    & ~ExtractionRun.provider.in_(("openrouter", "chatgpt")),
                )
            )
        )
    return list(db.scalars(statement))
