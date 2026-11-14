from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.db.processing import SearchChunk
from app.pipeline import embeddings
from tests.test_library import expo, upload


def chunk(db, text, document_id=None):
    row = SearchChunk(
        source_type="ocr",
        source_id=uuid4(),
        document_id=document_id,
        ordinal=0,
        text=text,
        text_revision=1,
    )
    db.add(row)
    db.flush()
    return row


def test_embed_job_always_embeds_its_own_chunk(engine, settings, monkeypatch):
    monkeypatch.setattr(
        embeddings, "encode", lambda texts, settings, query=False: [[0.0] * 384 for _ in texts]
    )
    with Session(engine) as db:
        # Older chunks still waiting, for example after a model change; they have no jobs.
        backlog = [chunk(db, f"FICTIONAL older chunk {n}") for n in range(40)]
        target = chunk(db, "FICTIONAL brochure page 33")
        embeddings.embed_batch(db, target.id, settings)
        assert target.embedding is not None
        assert target.model_version == embeddings.version(settings)
        # The batch stays bounded; the rest of the backlog is left for later jobs.
        assert sum(row.embedding is not None for row in backlog) == 31


def test_embed_job_prefers_chunks_from_the_same_document(signed_in, engine, settings, monkeypatch):
    monkeypatch.setattr(
        embeddings, "encode", lambda texts, settings, query=False: [[0.0] * 384 for _ in texts]
    )
    _, saved = upload(signed_in, expo(signed_in))
    document_id = UUID(saved["document"]["id"])
    with Session(engine) as db:
        backlog = [chunk(db, f"FICTIONAL older chunk {n}") for n in range(40)]
        pages = [chunk(db, f"FICTIONAL brochure page {n}", document_id) for n in range(5)]
        embeddings.embed_batch(db, pages[-1].id, settings)
        assert all(row.embedding is not None for row in pages)
        assert sum(row.embedding is not None for row in backlog) == 27
