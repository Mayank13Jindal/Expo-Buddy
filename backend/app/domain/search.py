import re
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.intelligence import Appearance
from app.db.library import Document
from app.db.processing import SearchChunk


def snippet(text: str, query: str, size: int = 260) -> str:
    words = re.findall(r"\w+", query.lower())
    position = min((text.lower().find(word) for word in words if word in text.lower()), default=0)
    start = max(0, position - 70)
    return (
        ("…" if start else "")
        + text[start : start + size]
        + ("…" if start + size < len(text) else "")
    )


def keyword_search(
    db: Session,
    query: str,
    *,
    expo_id: UUID | None = None,
    include_notes: bool = True,
    limit: int = 50,
    type: str | None = None,
    review_state: str | None = None,
    document_ids: list[UUID] | None = None,
) -> list[dict]:
    statement = select(SearchChunk, Document).outerjoin(
        Document, Document.id == SearchChunk.document_id
    )
    statement = statement.where(or_(Document.id.is_(None), Document.deleted_at.is_(None)))
    if expo_id:
        statement = statement.where(
            or_(
                SearchChunk.expo_id == expo_id,
                SearchChunk.company_id.in_(
                    select(Appearance.company_id).where(Appearance.expo_id == expo_id)
                ),
            )
        )
    if not include_notes:
        statement = statement.where(SearchChunk.source_type != "note")
    if type:
        statement = statement.where(Document.type == type)
    if review_state:
        from app.domain.review import review_filter

        statement = statement.where(review_filter(db, review_state))
    if document_ids is not None:
        statement = statement.where(Document.id.in_(document_ids))
    contains = SearchChunk.text.icontains(query, autoescape=True)
    if db.bind.dialect.name == "postgresql":
        terms = func.websearch_to_tsquery("english", query)
        match = SearchChunk.search_vector.op("@@")(terms)
        statement = statement.where(or_(contains, match)).order_by(
            contains.desc(),
            func.ts_rank_cd(SearchChunk.search_vector, terms).desc(),
        )
    else:
        statement = statement.where(contains)
    results, seen = [], set()
    for chunk, doc in db.execute(statement.limit(min(max(limit, 1), 50) * 4)):
        identity = str(doc.id) if doc else str(chunk.source_id)
        if identity in seen:
            continue
        seen.add(identity)
        results.append(
            {
                "id": identity,
                "document_id": str(doc.id) if doc else None,
                "title": doc.title if doc else "Personal note",
                "expo_id": str(chunk.expo_id) if chunk.expo_id else None,
                "company_id": str(chunk.company_id) if chunk.company_id else None,
                "snippet": snippet(chunk.text, query),
                "source_type": chunk.source_type,
                "match_kind": "keyword",
                "processing_state": doc.processing_state if doc else "ready",
                "page_id": str(chunk.page_id) if chunk.page_id else None,
                "source_id": str(chunk.source_id),
                "provisional": bool(doc and doc.group_state == "suggested"),
                "type": doc.type if doc else "note",
                "review_state": doc.review_state if doc else None,
            }
        )
        if len(results) >= min(max(limit, 1), 50):
            break
    return results
