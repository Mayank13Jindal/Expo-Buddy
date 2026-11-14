import threading
from functools import lru_cache
from pathlib import Path

from sqlalchemy import case, false, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.library import Document
from app.db.processing import Job, SearchChunk
from app.domain.jobs import WaitForResource

MODELS = {
    "minilm": ("minilm-1110a243fdf4", "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"),
    "bge": ("bge-5c38ec7c405e", "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"),
}
_encode_lock = threading.Lock()
BATCH_SIZE = 32


def version(settings: Settings) -> str:
    return settings.embedding_model + ":" + MODELS[settings.embedding_model][1]


@lru_cache(maxsize=2)
def model(folder: str):
    if not (Path(folder) / "model.safetensors").is_file():
        raise WaitForResource("Meaning search is waiting for the local search models.")
    import torch
    from sentence_transformers import SentenceTransformer

    torch.set_num_threads(2)
    return SentenceTransformer(folder, device="cpu", local_files_only=True, trust_remote_code=False)


def _encode(texts: list[str], settings: Settings, *, query: bool = False) -> list[list[float]]:
    engine = model(str(settings.models_dir / "embeddings" / MODELS[settings.embedding_model][0]))
    if query and settings.embedding_model == "bge":
        texts = [
            "Represent this sentence for searching relevant passages: " + text for text in texts
        ]
    return engine.encode(
        texts, normalize_embeddings=True, show_progress_bar=False, batch_size=16
    ).tolist()


def encode(texts: list[str], settings: Settings, *, query: bool = False) -> list[list[float]]:
    with _encode_lock:
        return _encode(texts, settings, query=query)


def embed_batch(db: Session, target, settings: Settings):
    desired = version(settings)
    first = db.get(SearchChunk, target)
    if not first:
        return
    # The job's own chunk always comes first, then the rest of its document, then the
    # oldest backlog. Otherwise a job could finish without embedding its own chunk and
    # leave the document stuck in "indexing".
    same_document = (
        SearchChunk.document_id == first.document_id if first.document_id else false()
    )
    rows = list(
        db.scalars(
            select(SearchChunk)
            .where(
                or_(
                    SearchChunk.embedding.is_(None),
                    SearchChunk.model_version != desired,
                    SearchChunk.embedding_text_revision != SearchChunk.text_revision,
                )
            )
            .order_by(
                case((SearchChunk.id == first.id, 0), (same_document, 1), else_=2),
                SearchChunk.created_at,
            )
            .limit(BATCH_SIZE)
        )
    )
    if not rows:
        return
    vectors = encode([row.text for row in rows], settings)
    for row, vector in zip(rows, vectors, strict=True):
        row.embedding, row.model_version, row.embedding_text_revision = (
            vector,
            desired,
            row.text_revision,
        )
    db.execute(
        update(Job)
        .where(
            Job.kind == "embed",
            Job.target_id.in_([row.id for row in rows]),
            Job.state.in_(("queued", "waiting")),
        )
        .values(state="succeeded")
    )
    db.flush()
    for id in {row.document_id for row in rows if row.document_id}:
        doc = db.get(Document, id)
        if doc and doc.processing_state == "indexing":
            stale = db.scalar(
                select(SearchChunk.id)
                .where(SearchChunk.document_id == id, SearchChunk.embedding.is_(None))
                .limit(1)
            )
            if not stale:
                doc.processing_state = "ready"
