import json
import re
from uuid import UUID

import httpx
from sqlalchemy import Float, func, or_, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.intelligence import Appearance, Company, Contact, ContactChannel
from app.db.library import Document
from app.db.processing import SearchChunk
from app.domain.search import keyword_search, snippet
from app.domain.search_filters import eligible_documents
from app.pipeline.embeddings import version


def rrf(*rankings: list[dict], k: int = 60) -> list[dict]:
    scores, rows = {}, {}
    for ranking in rankings:
        seen = set()
        rank = 0
        for row in ranking:
            id = row["document_id"] or row["id"]
            if id in seen:
                continue
            seen.add(id)
            rank += 1
            scores[id] = scores.get(id, 0) + 1 / (k + rank)
            rows.setdefault(id, row)
    return [rows[id] for id in sorted(scores, key=lambda id: -scores[id])]


def exact_search(db: Session, query: str, expo_id: UUID | None = None) -> list[dict]:
    from app.pipeline.ai import normalise_channel

    channel_ids = list(
        db.scalars(
            select(ContactChannel.owner_id).where(
                ContactChannel.deleted_at.is_(None),
                or_(
                    ContactChannel.normalised == query.casefold(),
                    ContactChannel.normalised == normalise_channel("phone", query)
                    if re.fullmatch(r"[+\d\s().xX-]+", query)
                    else False,
                ),
            )
        )
    )
    from urllib.parse import urlsplit

    digits = re.sub(r"\D", "", query)
    if len(digits) >= 5 and re.fullmatch(r"[+\d\s().xX-]+", query):
        channel_ids += list(
            db.scalars(
                select(ContactChannel.owner_id).where(
                    ContactChannel.kind == "phone",
                    ContactChannel.deleted_at.is_(None),
                    func.replace(ContactChannel.normalised, "+", "") == digits,
                )
            )
        )
    try:
        host = urlsplit(query if "://" in query else "https://" + query).hostname or ""
    except ValueError:
        host = ""
    host = host.casefold().removeprefix("www.")
    websites = []
    if "." in host and not any(char.isspace() for char in host):
        websites = [
            prefix + host + suffix
            for prefix in ("", "www.", "http://", "https://", "http://www.", "https://www.")
            for suffix in ("", "/")
        ]
    companies = set(
        db.scalars(
            select(Company.id).where(
                Company.deleted_at.is_(None),
                or_(
                    func.lower(Company.display_name) == query.casefold(),
                    Company.id.in_(channel_ids),
                    func.lower(Company.website).in_(websites),
                ),
            )
        )
    )
    companies.update(
        db.scalars(
            select(Contact.company_id).where(
                Contact.deleted_at.is_(None),
                or_(func.lower(Contact.full_name) == query.casefold(), Contact.id.in_(channel_ids)),
            )
        )
    )
    statement = select(Document).where(
        Document.company_id.in_(companies), Document.deleted_at.is_(None)
    )
    if expo_id:
        statement = statement.where(Document.expo_id == expo_id)
    return [
        {
            "id": str(doc.id),
            "document_id": str(doc.id),
            "company_id": str(doc.company_id),
            "expo_id": str(doc.expo_id),
            "title": doc.title,
            "snippet": query,
            "source_type": "field",
            "source_id": str(doc.company_id),
            "page_id": None,
            "provisional": doc.group_state == "suggested",
            "type": doc.type,
            "review_state": doc.review_state,
            "exact_match": True,
            "match_kind": "exact",
            "processing_state": doc.processing_state,
        }
        for doc in db.scalars(statement.limit(50))
    ]


def hybrid_search(
    db: Session,
    settings: Settings,
    query: str,
    *,
    expo_id: UUID | None = None,
    include_notes: bool = True,
    include_related: bool = False,
    limit: int = 50,
    type: str | None = None,
    review_state: str | None = None,
    company_id: UUID | None = None,
    **filters,
):
    document_ids = eligible_documents(db, company_id=company_id, **filters)
    keyword = keyword_search(
        db,
        query,
        expo_id=expo_id,
        include_notes=include_notes,
        limit=50,
        type=type,
        review_state=review_state,
        document_ids=document_ids,
    )
    semantic, available = [], False
    if include_related and query.replace(" ", "").isalpha():
        try:
            with httpx.Client(timeout=3, trust_env=False) as client:
                response = client.post(
                    settings.embedding_service_url + "/embed",
                    headers={"Authorization": "Bearer " + settings.internal_token},
                    json={"texts": [query], "query": True},
                )
                response.raise_for_status()
                vector = response.json()["vectors"][0]
            available = True
            if db.bind.dialect.name == "postgresql":
                distance = SearchChunk.embedding.op("<=>", return_type=Float)(
                    text("CAST(:query_vector AS vector)")
                )
                statement = (
                    select(SearchChunk, Document)
                    .outerjoin(Document, Document.id == SearchChunk.document_id)
                    .where(
                        SearchChunk.embedding.is_not(None),
                        SearchChunk.model_version == version(settings),
                        SearchChunk.embedding_text_revision == SearchChunk.text_revision,
                        or_(Document.id.is_(None), Document.deleted_at.is_(None)),
                        distance < 0.45,
                    )
                )
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
                for chunk, doc in db.execute(
                    statement.order_by(distance).limit(100), {"query_vector": json.dumps(vector)}
                ):
                    semantic.append(
                        {
                            "id": str(doc.id if doc else chunk.source_id),
                            "document_id": str(doc.id) if doc else None,
                            "title": doc.title if doc else "Personal note",
                            "company_id": str(chunk.company_id) if chunk.company_id else None,
                            "expo_id": str(chunk.expo_id) if chunk.expo_id else None,
                            "snippet": snippet(chunk.text, query),
                            "source_type": chunk.source_type,
                            "match_kind": "semantic",
                            "processing_state": doc.processing_state if doc else "ready",
                            "source_id": str(chunk.source_id),
                            "page_id": str(chunk.page_id) if chunk.page_id else None,
                            "type": doc.type if doc else "note",
                            "review_state": doc.review_state if doc else None,
                            "provisional": bool(doc and doc.group_state == "suggested"),
                        }
                    )
        except (httpx.HTTPError, KeyError, ValueError, OSError):
            available = False
    result = rrf(keyword, semantic)
    exact = exact_search(db, query, expo_id)
    seen = {row["id"] for row in exact}
    result = exact + [row for row in result if row["id"] not in seen]
    if document_ids is not None:
        result = [
            row for row in result if row.get("document_id") in {str(id) for id in document_ids}
        ]
    if type:
        result = [row for row in result if row.get("type") == type]
    from app.domain.review import document_status, pending

    proposals = pending(db, expo_id) if result else []
    for row in result:
        row['entity_type'] = 'note' if row['source_type'] == 'note' else 'document' if row.get('document_id') else 'company'
        if not row.get('document_id') and row['source_type'] != 'note':
            person = db.get(Contact, UUID(row['source_id']))
            if person:
                row['entity_type'], row['title'] = 'person', person.full_name
        if row['entity_type'] != 'document':
            row['type'] = row['entity_type']
        if row.get("document_id"):
            document = db.get(Document, UUID(row["document_id"]))
            if document:
                row.update(document_status(db, document, proposals))
        if row.get("company_id"):
            company = db.get(Company, UUID(row["company_id"]))
            if company:
                row["company_name"] = company.display_name
                row["contacts"] = [
                    {
                        "id": str(person.id),
                        "full_name": person.full_name,
                        "designation": person.designation,
                    }
                    for person in db.scalars(
                        select(Contact).where(
                            Contact.company_id == company.id, Contact.deleted_at.is_(None)
                        )
                    )
                ]
                if row["entity_type"] == "company":
                    row["title"] = company.display_name
    if review_state:
        result = [
            row
            for row in result
            if row.get("review_status", row.get("review_state")) == review_state
        ]
    return {
        "query": query,
        "results": result[: min(max(1, limit), 50)],
        "semantic_available": available,
    }
