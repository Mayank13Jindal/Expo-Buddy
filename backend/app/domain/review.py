"""Review comparisons shared by decisions, attention counts, and export warnings."""

import json

from sqlalchemy import select

from app.db.intelligence import Company, Contact, Proposal
from app.db.library import Asset, Document, DocumentPage, Preference
from app.domain.contact_values import (
    channel_issue,
    channel_key,
    contact_owner_issue,
    normalise_channel,
    person_evidence_issue,
)


def region_hint(db):
    return db.scalar(select(Preference.region_hint)) or None


def key(value, field, region=None):
    if field == "channels" and isinstance(value, dict):
        return channel_key(value, region)
    if isinstance(value, str):
        return " ".join(value.casefold().split())
    return json.dumps(value, sort_keys=True)


def changes(field, current, proposed, region=None):
    if isinstance(current, list) and isinstance(proposed, list):
        old = {key(item, field, region): item for item in current}
        new = {key(item, field, region): item for item in proposed}
        result = [
            {"operation": "remove", "value": item}
            for identity, item in old.items()
            if identity not in new
        ]
        result += [
            {"operation": "add", "value": item}
            for identity, item in new.items()
            if identity not in old
        ]
        return result
    if key(current, field, region) == key(proposed, field, region):
        return []
    return [{"operation": "replace", "value": proposed}]


def pending(db, expo_id=None):
    region = region_hint(db)
    result = []
    for row in db.scalars(
        select(Proposal).where(Proposal.state == "pending").order_by(Proposal.created_at)
    ):
        from app.domain.fields import FIELDS, MODELS

        entity = (
            db.get(MODELS.get(row.entity_type), row.entity_id)
            if row.entity_type in MODELS
            else None
        )
        if (
            entity is None
            or row.field not in FIELDS.get(row.entity_type, set())
            or getattr(entity, "deleted_at", None)
        ):
            continue
        if expo_id:
            statement = select(Document.id).where(
                Document.expo_id == expo_id, Document.deleted_at.is_(None)
            )
            if row.entity_type == "company":
                statement = statement.where(Document.company_id == row.entity_id)
            elif row.entity_type == "contact":
                statement = statement.where(Document.id == entity.source_document_id)
            else:
                statement = statement.where(Document.id == row.entity_id)
            if row.document_id:
                statement = select(Document.id).where(
                    Document.id == row.document_id,
                    Document.expo_id == expo_id,
                    Document.deleted_at.is_(None),
                )
            if db.scalar(statement) is None:
                continue
        if changes(row.field, getattr(entity, row.field), row.proposed_value, region):
            result.append(row)
    return result


def for_document(db, doc, proposals=None):
    proposals = pending(db) if proposals is None else proposals
    if not proposals:
        return []
    contact_ids = (
        set(db.scalars(select(Contact.id).where(Contact.source_document_id == doc.id)))
        if any(row.entity_type == "contact" for row in proposals)
        else set()
    )
    return [
        row
        for row in proposals
        if row.document_id == doc.id
        or (row.entity_type == "document" and row.entity_id == doc.id)
        or (row.entity_type == "company" and row.entity_id == doc.company_id)
        or (row.entity_type == "contact" and row.entity_id in contact_ids)
    ]


def warning(db, doc, proposals=None):
    reasons = []
    if doc.review_state != "reviewed":
        reasons.append(
            "Needs attention" if doc.review_state == "needs_attention" else "Not reviewed"
        )
    if for_document(db, doc, proposals):
        reasons.append("Unresolved suggested changes")
    return "; ".join(reasons)


def proposal_view(db, row):
    from app.api.library import record
    from app.domain.fields import entity

    target = entity(db, row.entity_type, row.entity_id)
    current = getattr(target, row.field)
    region = region_hint(db)
    items = changes(row.field, current, row.proposed_value, region)
    comparisons = []
    for index, item in enumerate(items):
        value = item["value"]
        issue = (
            (
                channel_issue(value, region)
                or contact_owner_issue(db, row.entity_type, row.entity_id, value, region)
                or (
                    person_evidence_issue(db, target, value) if row.entity_type == "contact" else ""
                )
            )
            if row.field == "channels" and item["operation"] != "remove"
            else ""
        )
        association_warning = ""
        if (
            row.entity_type == "contact"
            and row.field == "channels"
            and item["operation"] == "add"
            and value.get("kind") in ("phone", "email")
            and target.source_document_id
        ):
            people = list(
                db.scalars(
                    select(Contact.id).where(
                        Contact.source_document_id == target.source_document_id,
                        Contact.deleted_at.is_(None),
                    )
                )
            )
            if len(people) > 1:
                association_warning = "Check person ownership: this card has multiple people. Verify the named person owns this value before accepting."
        text = value.get("raw", "") if isinstance(value, dict) else value
        comparisons.append(
            {
                "index": index,
                "operation": item["operation"],
                "before": current
                if item["operation"] == "replace"
                else text
                if item["operation"] == "remove"
                else "",
                "after": text if item["operation"] != "remove" else "",
                "label": value.get("kind", "")
                if isinstance(value, dict)
                else row.field.replace("_", " "),
                "normalised": normalise_channel(value["kind"], value["raw"], region)
                if isinstance(value, dict) and row.field == "channels"
                else "",
                "warning": issue
                or association_warning
                or (
                    "Compare the address spelling with the source."
                    if isinstance(value, dict) and value.get("kind") == "address"
                    else ""
                ),
                "can_accept": not bool(issue),
            }
        )
    source_id = row.document_id or (
        target.id if row.entity_type == "document" else getattr(target, "source_document_id", None)
    )
    if not source_id and row.entity_type == "company":
        source_id = db.scalar(
            select(Document.id)
            .where(Document.company_id == target.id, Document.deleted_at.is_(None))
            .order_by(Document.created_at)
        )
    page = (
        db.scalar(
            select(DocumentPage)
            .where(DocumentPage.document_id == source_id)
            .order_by(DocumentPage.order)
        )
        if source_id
        else None
    )
    if row.evidence:
        from uuid import UUID

        try:
            evidence_page = db.get(DocumentPage, UUID(row.evidence[0].get("page_id", "")))
            if evidence_page:
                page, source_id = evidence_page, evidence_page.document_id
        except (ValueError, TypeError):
            pass
    company = (
        db.get(Company, target.company_id)
        if row.entity_type == "contact"
        else target
        if row.entity_type == "company"
        else None
    )
    duplicates = []
    if (
        row.field == "channels"
        and isinstance(current, list)
        and isinstance(row.proposed_value, list)
    ):
        existing = {channel_key(value, region): value for value in current}
        for value in row.proposed_value:
            match = existing.get(channel_key(value, region))
            if match and match.get("raw") != value.get("raw"):
                duplicates.append(f"{value['raw']} is already saved as {match['raw']}.")
    return {
        **record(row),
        "current_value": current,
        "record_name": getattr(target, "full_name", None)
        or getattr(target, "display_name", None)
        or getattr(target, "title", "Unnamed record"),
        "company_name": company.display_name if company else "",
        "document_id": source_id,
        "page_id": page.id if page else None,
        "asset_id": page.asset_id if page else None,
        "source_page": (
            {**record(page), "asset": record(db.get(Asset, page.asset_id))} if page else None
        ),
        "changes": comparisons,
        "duplicate_warnings": duplicates,
        "stale": current != row.current_value,
    }


def document_status(db, doc, proposals=None):
    count = len(for_document(db, doc, proposals))
    return {
        "review_status": "needs_attention" if count else doc.review_state,
        "pending_changes": count,
    }


def review_filter(db, state):
    from sqlalchemy import or_

    proposals = pending(db)
    linked = or_(
        Document.id.in_(
            [
                row.document_id or row.entity_id
                for row in proposals
                if row.document_id or row.entity_type == "document"
            ]
        ),
        Document.company_id.in_(
            [row.entity_id for row in proposals if row.entity_type == "company"]
        ),
        Document.id.in_(
            select(Contact.source_document_id).where(
                Contact.id.in_([row.entity_id for row in proposals if row.entity_type == "contact"])
            )
        ),
    )
    return (
        or_(Document.review_state == state, linked)
        if state == "needs_attention"
        else (Document.review_state == state) & ~linked
    )


def contact_status(db, person, proposals=None):
    from app.db.intelligence import Appearance

    proposals = pending(db) if proposals is None else proposals
    ids = set(db.scalars(select(Appearance.document_id).where(Appearance.contact_id == person.id)))
    if person.source_document_id:
        ids.add(person.source_document_id)
    docs = list(
        db.scalars(select(Document).where(Document.id.in_(ids), Document.deleted_at.is_(None)))
    )
    related = {row.id for doc in docs for row in for_document(db, doc, proposals)}
    related.update(
        row.id for row in proposals if row.entity_type == "contact" and row.entity_id == person.id
    )
    states = [doc.review_state for doc in docs]
    state = (
        "needs_attention"
        if related or "needs_attention" in states
        else "reviewed"
        if states and all(value == "reviewed" for value in states)
        else "unreviewed"
    )
    return {
        "review_status": state,
        "pending_changes": len(related),
        "review_warning": ""
        if state == "reviewed"
        else "Source needs review — verify these contact details."
        if docs or related
        else "No linked scan to verify these contact details.",
    }
