"""Hand-checked examples compare against raw AI output, never corrected records."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.dependencies import DB, OwnerSession
from app.api.library import find
from app.db.intelligence import Company, Contact
from app.db.library import Document
from app.db.processing import ExtractionRun

router = APIRouter(prefix="/api/v1/accuracy", tags=["accuracy"])
FIELDS = {"company_name", "people", "phones", "emails"}


def from_record(db, doc):
    company = db.get(Company, doc.company_id) if doc.company_id else None
    people = list(
        db.scalars(
            select(Contact).where(
                Contact.source_document_id == doc.id, Contact.deleted_at.is_(None)
            )
        )
    )
    channels = (company.channels if company else []) + [
        item for person in people for item in person.channels
    ]
    return {
        "company_name": company.display_name if company else "",
        "people": sorted(person.full_name for person in people),
        "phones": sorted({item["raw"] for item in channels if item["kind"] == "phone"}),
        "emails": sorted({item["raw"] for item in channels if item["kind"] == "email"}),
    }


def raw_output(runs):
    name, people, channels = "", [], []
    for run in runs:
        value = run.output.get("data", {})
        name = (value.get("company_name") or {}).get("value") or name
        for person in value.get("people", []):
            if person.get("full_name"):
                people.append(person["full_name"]["value"])
            channels += person.get("channels", [])
        channels += value.get("channels", [])
    return {
        "company_name": name,
        "people": sorted(set(people)),
        "phones": sorted({item["raw"] for item in channels if item["kind"] == "phone"}),
        "emails": sorted({item["raw"] for item in channels if item["kind"] == "email"}),
    }


class Example(BaseModel):
    confirmed: bool
    checked_fields: list[str] = Field(min_length=1, max_length=4)


@router.post("/examples/{id}")
def add_example(id: UUID, body: Example, session: OwnerSession, db: DB):
    doc = find(db, Document, id)
    if (
        not body.confirmed
        or doc.review_state != "reviewed"
        or not set(body.checked_fields) <= FIELDS
    ):
        raise HTTPException(
            422,
            "Compare with the original, correct and mark reviewed, then confirm which fields you checked.",
        )
    expected = from_record(db, doc)
    doc.processing_options = {
        **doc.processing_options,
        "benchmark": {
            "expected": {field: expected[field] for field in body.checked_fields},
            "checked_at": datetime.now(UTC).isoformat(),
        },
    }
    db.commit()
    return {"saved": True}


@router.get("")
def report(session: OwnerSession, db: DB):
    examples, correct, measured = [], 0, 0
    for doc in db.scalars(select(Document).where(Document.deleted_at.is_(None))):
        expected = doc.processing_options.get("benchmark", {}).get("expected")
        if expected is None:
            continue
        runs = list(
            db.scalars(
                select(ExtractionRun)
                .where(
                    ExtractionRun.document_id == doc.id,
                    ExtractionRun.stage == "ai",
                    ExtractionRun.status == "succeeded",
                )
                .order_by(ExtractionRun.input_revision.desc())
            )
        )
        if runs:
            latest = runs[0].input_revision
            runs = [run for run in runs if run.input_revision == latest]
            actual = raw_output(runs)
            matches = {key: actual[key] == value for key, value in expected.items()}
            correct += sum(matches.values())
            measured += len(matches)
        else:
            matches = None
        examples.append(
            {
                "document_id": str(doc.id),
                "title": doc.title,
                "matches": matches,
                "model": runs[0].model if runs else None,
                "input_revision": runs[0].input_revision if runs else None,
            }
        )
    return {
        "examples": examples,
        "correct_field_groups": correct,
        "measured_field_groups": measured,
        "exact_match_percent": round(100 * correct / measured, 1) if measured else None,
        "policy": "Exact matches to owner-confirmed ground truth, compared with raw AI output. A phone/email group must match completely. This is not a population accuracy estimate.",
    }
