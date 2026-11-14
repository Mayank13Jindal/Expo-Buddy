from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.db.library import Document
from app.domain.hybrid import hybrid_search
from tests.test_library import expo, upload


def test_contact_review_warning_follows_source_into_people_and_company(signed_in, engine):
    _, saved = upload(signed_in, expo(signed_in))
    doc_id = saved["document"]["id"]
    company = signed_in.post(
        "/api/v1/companies", json={"fields": {"display_name": "FICTIONAL Warning Company"}}
    ).json()
    signed_in.post(
        f"/api/v1/documents/{doc_id}/attach-company", json={"company_id": company["id"]}
    ).raise_for_status()
    person = signed_in.post(
        "/api/v1/contacts",
        json={
            "company_id": company["id"],
            "document_id": doc_id,
            "fields": {
                "full_name": "FICTIONAL Warning Person",
                "channels": [{"kind": "email", "raw": "uncertain@example.com"}],
            },
        },
    ).json()
    with Session(engine) as db:
        doc = db.get(Document, UUID(doc_id))
        doc.review_state = "needs_attention"
        doc.review_reasons = ["Synthetic email uncertainty"]
        db.commit()
    row = next(row for row in signed_in.get("/api/v1/contacts").json() if row["id"] == person["id"])
    assert row["review_status"] == "needs_attention" and row["review_warning"]
    detail = signed_in.get("/api/v1/companies/" + company["id"]).json()
    assert detail["review_warning"] and detail["contacts"][0]["review_warning"]
    signed_in.post(f"/api/v1/review/{doc_id}/resolve", json={}).raise_for_status()
    assert not signed_in.get("/api/v1/companies/" + company["id"]).json()["contacts"][0][
        "review_warning"
    ]


def test_company_field_search_is_not_labelled_as_a_personal_note(signed_in, engine, settings):
    company = signed_in.post(
        "/api/v1/companies", json={"fields": {"display_name": "FICTIONAL Unique Lookup Company"}}
    ).json()
    with Session(engine) as db:
        result = hybrid_search(db, settings, "Unique Lookup")
        assert result["results"]
        row = result["results"][0]
        assert row["entity_type"] == "company" and row["type"] == "company"
        assert row["company_id"] == company["id"] and not row["document_id"]
        assert row["title"] == "FICTIONAL Unique Lookup Company"


def test_invalid_and_missing_document_links_have_accurate_errors(signed_in):
    for id in ("invalid-document-id", str(uuid4())):
        response = signed_in.get("/api/v1/documents/" + id)
        assert response.status_code == 404
        assert "form" not in response.json()["detail"].lower()


def test_restore_finalization_preserves_notes_and_requires_reconnection(signed_in, engine):
    from sqlalchemy import select

    from app.core.restore_finalize import finalize
    from app.db.agent import APIToken
    from app.db.intelligence import ProviderSetting
    from app.db.library import Note, Owner
    from app.db.library import Session as Login
    from app.domain import providers

    event = expo(signed_in)
    with Session(engine) as db:
        db.add(Note(expo_id=UUID(event), text="SYNTHETIC private restore note"))
        token = APIToken(name="Synthetic restore token", token_hash="a" * 64, scopes=["read"])
        db.add(token)
        rows = providers.ensure_providers(db)
        provider_data = [
            {
                "id": str(row.id),
                "provider": row.provider,
                "order": row.order,
                "model": row.model,
                "config": {},
            }
            for row in rows
        ]
        for row in rows:
            row.enabled = True
            row.encrypted_secret = "FAKE-" + str(uuid4())
        db.scalar(select(Owner)).settings = {"cloud_fallback": True}
        db.commit()
        finalize(db, provider_data)
        assert db.scalar(select(Note)).text == "SYNTHETIC private restore note"
        assert token.revoked_at and not list(db.scalars(select(Login)))
        assert all(
            not row.encrypted_secret and not row.enabled
            for row in db.scalars(select(ProviderSetting))
        )
        assert not db.scalar(select(Owner)).settings["cloud_fallback"]


def test_corrected_person_name_does_not_create_duplicate_on_reprocessing(signed_in, engine):
    from sqlalchemy import select

    from app.db.intelligence import Contact
    from app.db.library import DocumentPage
    from app.db.processing import ExtractionRun
    from app.domain import fields
    from app.pipeline.ai import apply_extraction
    from tests.test_ai import sample

    _, saved = upload(signed_in, expo(signed_in))
    with Session(engine) as db:
        doc = db.get(Document, UUID(saved["document"]["id"]))
        page = db.scalar(select(DocumentPage).where(DocumentPage.document_id == doc.id))
        value, pages = sample(page.id)
        run = ExtractionRun(
            document_id=doc.id,
            stage="ai",
            provider="synthetic",
            input_revision=1,
            status="succeeded",
        )
        db.add(run)
        db.flush()
        apply_extraction(db, doc, value, pages, run)
        person = db.scalar(select(Contact))
        fields.set_field(db, "contact", person.id, "full_name", "Corrected Fictional Person")
        db.commit()
        value.people[0].full_name.value = "Corrected Fictional Person"
        value.people[0].full_name.evidence.quote = "Corrected Fictional Person"
        pages[str(page.id)] = pages[str(page.id)].replace(
            "FAKE PERSON", "Corrected Fictional Person"
        )
        apply_extraction(db, doc, value, pages, run)
        db.commit()
        assert len(list(db.scalars(select(Contact)))) == 1
        assert person.full_name == "Corrected Fictional Person"
