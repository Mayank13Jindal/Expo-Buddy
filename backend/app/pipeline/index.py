import os
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.library import Document, DocumentPage, Note
from app.db.processing import Job, SearchChunk


def chunks(value: str, size: int = 190, overlap: int = 35) -> list[str]:
    model = os.getenv("EMBEDDING_MODEL", "minilm")
    from app.pipeline.embeddings import MODELS

    path = (
        Path(os.getenv("MODELS_DIR", "/data/models"))
        / "embeddings"
        / MODELS[model][0]
        / "tokenizer.json"
    )
    if path.is_file():
        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_file(str(path))
        tokenizer.no_padding()
        tokenizer.no_truncation()
        offsets = tokenizer.encode(value, add_special_tokens=False).offsets
        return [
            value[offsets[start][0] : offsets[min(start + 200, len(offsets)) - 1][1]]
            for start in range(0, len(offsets), 160)
        ]
    words = value.split()
    return [" ".join(words[start : start + size]) for start in range(0, len(words), size - overlap)]


def index_text(
    db: Session,
    source_type: str,
    source_id: UUID,
    text: str,
    revision: int,
    *,
    document: Document | None = None,
    page_id: UUID | None = None,
    expo_id: UUID | None = None,
    company_id: UUID | None = None,
) -> None:
    from sqlalchemy import update

    from app.domain.jobs import enqueue

    old_ids = list(
        db.scalars(
            select(SearchChunk.id).where(
                SearchChunk.source_type == source_type, SearchChunk.source_id == source_id
            )
        )
    )
    if old_ids:
        db.execute(
            update(Job)
            .where(
                Job.kind == "embed",
                Job.target_id.in_(old_ids),
                Job.state.in_(("queued", "waiting")),
            )
            .values(state="cancelled")
        )
    db.execute(
        delete(SearchChunk).where(
            SearchChunk.source_type == source_type, SearchChunk.source_id == source_id
        )
    )
    for number, value in enumerate(chunks(text)):
        chunk = SearchChunk(
            source_type=source_type,
            source_id=source_id,
            ordinal=number,
            text=value,
            text_revision=revision,
            document_id=document.id if document else None,
            expo_id=document.expo_id if document else expo_id,
            company_id=document.company_id if document else company_id,
            page_id=page_id,
        )
        db.add(chunk)
        db.flush()
        enqueue(db, "embed", chunk.id, revision)


def rebuild_index(db: Session):
    from app.db.intelligence import Company, Contact
    from app.db.processing import OCRResult
    from app.domain.fields import index_entity
    from app.domain.tags import index_tags

    for doc in db.scalars(select(Document).where(Document.deleted_at.is_(None))):
        index_tags(db, doc)
        for page in db.scalars(select(DocumentPage).where(DocumentPage.document_id == doc.id)):
            ocr = db.scalar(
                select(OCRResult)
                .where(OCRResult.document_page_id == page.id)
                .order_by(OCRResult.revision.desc())
                .limit(1)
            )
            if ocr:
                index_text(
                    db, "page", page.id, ocr.text, ocr.revision, document=doc, page_id=page.id
                )
    for note in db.scalars(select(Note)):
        index_note(db, note)
    for kind, model in (("company", Company), ("contact", Contact)):
        for row in db.scalars(select(model).where(model.deleted_at.is_(None))):
            index_entity(db, kind, row)


def index_note(db: Session, note: Note) -> None:
    doc = db.get(Document, note.document_id) if note.document_id else None
    if not doc and note.asset_id:
        doc = db.scalar(
            select(Document)
            .join(DocumentPage)
            .where(DocumentPage.asset_id == note.asset_id, Document.deleted_at.is_(None))
        )
    from app.db.capture import CaptureGroup

    group = db.get(CaptureGroup, note.capture_group_id) if note.capture_group_id else None
    index_text(
        db,
        "note",
        note.id,
        "" if note.deleted_at else note.text,
        1,
        document=doc,
        expo_id=note.expo_id or (group.expo_id if group else None),
        company_id=note.company_id,
    )
