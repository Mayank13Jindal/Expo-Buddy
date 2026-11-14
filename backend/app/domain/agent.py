import secrets
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select

from app.api.dependencies import aware
from app.api.intelligence import company_detail
from app.api.library import find, record
from app.core.security import digest
from app.db.agent import AgentAudit, APIToken
from app.db.exports import Export
from app.db.intelligence import Contact, FieldValue
from app.db.library import Document, DocumentPage, Expo, Note, Preference, now
from app.db.processing import OCRResult
from app.domain import dashboard, exports, fields, tags
from app.domain.hybrid import hybrid_search
from app.exports.schema import Selection
from app.pipeline.index import index_note

SCOPES = {"read", "notes", "write", "export"}
TOOLS = {
    "list_expos": "read",
    "dashboard_summary": "read",
    "search_library": "read",
    "get_company": "read",
    "get_contact": "read",
    "get_document_text": "read",
    "list_review_queue": "read",
    "find_companies_by_capability": "read",
    "add_note": "write",
    "add_tags": "write",
    "propose_field_change": "write",
    "create_export": "export",
    "get_export_status": "export",
}


def issue(db, name, scopes, expires_at=None):
    scopes = sorted(set(scopes) | {"read"})
    if not set(scopes) <= SCOPES:
        raise HTTPException(422, "Choose read, notes, write or export scopes.")
    secret = "expo_" + secrets.token_urlsafe(36)
    row = APIToken(name=name, scopes=scopes, token_hash=digest(secret), expires_at=expires_at)
    db.add(row)
    db.flush()
    return row, secret


def validate(db, raw, *, rate_limit=False):
    row = (
        db.scalar(select(APIToken).where(APIToken.token_hash == digest(raw)).with_for_update())
        if raw and len(raw) < 256
        else None
    )
    if not row or row.revoked_at or (row.expires_at and aware(row.expires_at) <= now()):
        raise HTTPException(401, "This agent token is missing, expired or revoked.")
    if rate_limit:
        minute = now().strftime("%Y-%m-%dT%H:%M")
        if row.minute != minute:
            row.minute, row.calls = minute, 0
        if row.calls >= 60:
            raise HTTPException(
                429, "This agent has reached 60 requests this minute. Try again shortly."
            )
        row.calls += 1
    row.last_used_at = now()
    return row


def audit(db, token_id, tool, arguments, status):
    summary = {"argument_names": sorted(arguments.keys())}
    for key in ("id", "entity_id", "document_id", "company_id", "expo_id", "offset", "limit"):
        if key in arguments:
            summary[key] = str(arguments[key])[:100]
    if "query" in arguments:
        summary["query_length"] = len(str(arguments["query"]))
    db.add(AgentAudit(token_id=token_id, tool=tool[:100], arguments_summary=summary, status=status))


def require_scope(token, scope):
    if token.revoked_at or (token.expires_at and aware(token.expires_at) <= now()):
        raise HTTPException(401, "This agent token expired or was revoked.")
    if scope not in token.scopes:
        raise HTTPException(
            403,
            f"This token needs the {scope} scope. The owner can create a token with that scope in Settings.",
        )


def invoke(db, settings, token, tool, arguments):
    require_scope(token, TOOLS[tool])
    include_notes = "notes" in token.scopes
    active = db.scalar(select(Preference.active_expo_id).limit(1))
    if tool == "list_expos":
        return [
            {
                "id": row.id,
                "name": row.name,
                "city": row.city,
                "archived": row.archived,
                "active": row.id == active,
                "counts": {
                    key: value
                    for key, value in dashboard.summary(
                        db, row.id, include_notes=include_notes, settings=settings
                    ).items()
                    if key in ("companies", "contacts", "documents", "notes")
                },
            }
            for row in db.scalars(select(Expo).order_by(Expo.created_at.desc()).limit(200))
        ]
    if tool == "dashboard_summary":
        result = dashboard.summary(
            db, arguments.get("expo_id") or active, include_notes=include_notes, settings=settings
        )
        result.pop("phone_queue", None)
        result.pop("activity", None)
        return result
    if tool in ("search_library", "find_companies_by_capability"):
        query = arguments["query"]
        filters = arguments.get("filters") or {}
        result = hybrid_search(
            db,
            settings,
            query,
            expo_id=None if arguments.get("all_expos") else arguments.get("expo_id") or active,
            include_notes=include_notes,
            include_related=tool == "find_companies_by_capability",
            limit=min(50, max(1, arguments.get("limit", 20))),
            **{
                key: value
                for key, value in filters.items()
                if key in ("type", "review_state", "company_id", "tag", "category", "processed_by")
            },
        )
        for row in result["results"]:
            row["app_link"] = (
                f"{settings.canonical_origin}/documents/{row['document_id']}"
                if row.get("document_id")
                else f"{settings.canonical_origin}/companies/{row['company_id']}"
                if row.get("company_id")
                else f"{settings.canonical_origin}/expos"
            )
        return result
    if tool == "get_company":
        result = company_detail(db, UUID(str(arguments["id"])), include_notes=include_notes)
        return result
    if tool == "get_contact":
        row = find(db, Contact, UUID(str(arguments["id"])))
        return {
            **record(row),
            "field_sources": [
                record(value)
                for value in db.scalars(
                    select(FieldValue).where(
                        FieldValue.entity_type == "contact",
                        FieldValue.entity_id == row.id,
                        FieldValue.is_current.is_(True),
                    )
                )
            ],
        }
    if tool == "get_document_text":
        id = UUID(str(arguments["id"]))
        doc = find(db, Document, id)
        if doc.deleted_at:
            raise HTTPException(404, "This document is in Trash.")
        offset, length = (
            max(0, arguments.get("offset", 0)),
            min(12000, max(1, arguments.get("length", 10000))),
        )
        # Page retrieval is bounded; large documents use a cursor over their complete source transcript.
        consumed, output, total = 0, "", 0
        for page in db.scalars(
            select(DocumentPage).where(DocumentPage.document_id == id).order_by(DocumentPage.order)
        ):
            ocr = db.scalar(
                select(OCRResult)
                .where(OCRResult.document_page_id == page.id)
                .order_by(OCRResult.revision.desc())
                .limit(1)
            )
            part = f"\n--- Page {page.order + 1}; source {page.id} ---\n" + (
                ocr.text if ocr else "[Text is still being read]"
            )
            start = max(0, offset - consumed)
            if start < len(part) and len(output) < length:
                output += part[start : start + length - len(output)]
            consumed += len(part)
            total += len(part)
        return {
            "document_id": id,
            "offset": offset,
            "text": output,
            "next_offset": offset + len(output) if offset + len(output) < total else None,
            "app_link": f"{settings.canonical_origin}/documents/{id}",
        }
    if tool == "list_review_queue":
        statement = select(Document).where(
            Document.deleted_at.is_(None), Document.review_state == "needs_attention"
        )
        if arguments.get("expo_id"):
            statement = statement.where(Document.expo_id == arguments["expo_id"])
        return [
            {
                "id": row.id,
                "title": row.title,
                "reasons": row.review_reasons,
                "app_link": f"{settings.canonical_origin}/documents/{row.id}",
            }
            for row in db.scalars(statement.limit(50))
        ]
    if tool == "add_note":
        id = UUID(str(arguments["entity_id"]))
        kind = arguments["entity_type"]
        if kind not in ("company", "document"):
            raise HTTPException(422, "Add a note to a company or document.")
        fields.entity(db, kind, id)
        client_uuid = arguments.get("client_uuid") or uuid4()
        existing = db.scalar(select(Note).where(Note.client_uuid == client_uuid))
        if existing:
            return {"id": existing.id, "saved": True}
        note = Note(
            **{f"{kind}_id": id},
            text=arguments["text"],
            client_uuid=client_uuid,
            origin=f"added by agent: {token.name}",
        )
        db.add(note)
        db.flush()
        index_note(db, note)
        return {"id": note.id, "saved": True}
    if tool == "add_tags":
        rows = tags.assign(
            db,
            arguments["entity_type"],
            UUID(str(arguments["entity_id"])),
            arguments["labels"],
            actor=f"agent: {token.name}",
        )
        return {"saved": True, "tags": [row.label for row in rows]}
    if tool == "propose_field_change":
        row = fields.proposal(
            db,
            arguments["entity_type"],
            UUID(str(arguments["entity_id"])),
            arguments["field"],
            arguments["value"],
            reason="An agent suggested this change. Check the source before accepting.",
            actor=f"agent: {token.name}",
        )
        return {
            "proposal_id": row.id if row else None,
            "state": row.state if row else "unchanged",
            "field_unchanged": True,
        }
    if tool == "create_export":
        selection = Selection.model_validate(arguments["selection"])
        row = exports.create(
            db, selection, settings, active, token_id=token.id, include_notes=include_notes
        )
        return {"export_id": row.id, "state": row.state, "counts": row.counts}
    if tool == "get_export_status":
        row = find(db, Export, UUID(str(arguments["id"])))
        if row.token_id != token.id:
            raise HTTPException(403, "This export belongs to a different token.")
        result = {"export_id": row.id, "state": row.state, "counts": row.counts, "error": row.error}
        if row.state == "ready" and row.expires_at and aware(row.expires_at) > now():
            nonce = secrets.token_urlsafe(32)
            row.download_hash, row.download_until = digest(nonce), now() + timedelta(minutes=5)
            result.update(
                download_url=f"{settings.canonical_origin}/api/v1/agent-download/{row.id}?ticket={nonce}",
                expires_at=row.download_until,
                authorization="Use the same Bearer token for this download.",
            )
        return result
    raise HTTPException(404, "This agent action is unavailable.")
