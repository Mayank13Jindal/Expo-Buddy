"""Regressions for the follow-up audit, using disposable records only."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.intelligence import Contact, Proposal
from app.db.library import Document, DocumentPage, Owner
from app.db.processing import ExtractionRun
from app.domain import fields, providers
from app.domain.hybrid import exact_search
from app.domain.review import proposal_view
from app.pipeline.ai import apply_extraction
from app.providers.schema import Extraction
from tests.test_library import expo, upload


def test_default_search_does_not_call_meaning_service_or_match_gibberish(signed_in, monkeypatch):
    import app.domain.hybrid as hybrid

    def forbidden(*args, **kwargs):
        raise AssertionError("Default search must not request embeddings.")

    monkeypatch.setattr(hybrid.httpx, "Client", forbidden)
    _, saved = upload(signed_in, expo(signed_in))
    signed_in.post(
        "/api/v1/notes",
        json={
            "document_id": saved["document"]["id"],
            "text": "Fictional solar mounting structures",
        },
    )
    for suffix in ("", "&include_related=true"):
        result = signed_in.get("/api/v1/search?q=zzqvwx987654321&scope=all" + suffix)
        assert result.status_code == 200, result.text
        assert not result.json()["results"]
    result = signed_in.get("/api/v1/search?q=mounting&scope=all").json()
    assert result["results"] and all(row["match_kind"] == "keyword" for row in result["results"])


def test_letters_and_digits_are_not_reinterpreted_as_a_phone(signed_in, engine):
    event = expo(signed_in)
    _, saved = upload(signed_in, event)
    company = signed_in.post(
        "/api/v1/companies",
        json={
            "fields": {
                "display_name": "Fictional phone company",
                "channels": [{"kind": "phone", "raw": "+12025550101"}],
            }
        },
    ).json()
    signed_in.post(
        f"/api/v1/documents/{saved['document']['id']}/attach-company",
        json={"company_id": company["id"]},
    )
    with Session(engine) as db:
        assert exact_search(db, "+1 (202) 555-0101")
        assert not exact_search(db, "zzqvwx12025550101")


def test_multi_person_contact_details_require_ownership_evidence(signed_in, engine):
    _, saved = upload(signed_in, expo(signed_in))
    with Session(engine) as db:
        doc = db.get(Document, UUID(saved["document"]["id"]))
        page = db.scalar(select(DocumentPage).where(DocumentPage.document_id == doc.id))

        def evidence(text):
            return {"page_id": str(page.id), "quote": text}

        data = {
            "people": [
                {
                    "full_name": {"value": name, "evidence": evidence(name)},
                    "channels": [{"kind": "phone", "raw": phone, "evidence": evidence(phone)}],
                }
                for name, phone in [
                    ("Fictional Alice", "+12025550101"),
                    ("Fictional Bob", "+12025550102"),
                ]
            ]
        }
        run = ExtractionRun(
            document_id=doc.id,
            stage="ai",
            provider="synthetic",
            input_revision=1,
            status="succeeded",
        )
        db.add(run)
        db.flush()
        apply_extraction(
            db,
            doc,
            Extraction.model_validate(data),
            {str(page.id): "Fictional Alice\nFictional Bob\n+12025550101\n+12025550102"},
            run,
        )
        db.commit()
        assert all(not person.channels for person in db.scalars(select(Contact)))
        assert not list(db.scalars(select(Proposal).where(Proposal.field == "channels")))
        assert any("association is uncertain" in reason for reason in doc.review_reasons)


def test_proposal_cannot_add_another_persons_saved_phone(signed_in, engine):
    company = signed_in.post(
        "/api/v1/companies", json={"fields": {"display_name": "Fictional association company"}}
    ).json()
    people = [
        signed_in.post(
            "/api/v1/contacts",
            json={"company_id": company["id"], "fields": {"full_name": name, "channels": channels}},
        ).json()
        for name, channels in [
            ("Fictional Alice", [{"kind": "phone", "raw": "+12025550101"}]),
            ("Fictional Bob", []),
        ]
    ]
    with Session(engine) as db:
        row = fields.proposal(
            db,
            "contact",
            UUID(people[1]["id"]),
            "channels",
            [{"kind": "phone", "raw": "+1 202 555 0101"}],
            reason="Synthetic OCR association",
        )
        db.commit()
        view = proposal_view(db, row)
        assert not view["changes"][0]["can_accept"]
        assert "Fictional Alice" in view["changes"][0]["warning"]
        id = row.id
    result = signed_in.post(f"/api/v1/proposals/{id}/accept", json={"selected_changes": [0]})
    assert result.status_code == 422
    assert not signed_in.get(f"/api/v1/contacts/{people[1]['id']}").json()["channels"]


def test_dashboard_agrees_with_settings_about_account_and_processing(
    signed_in, engine, monkeypatch
):
    from app.providers import chatgpt

    monkeypatch.setattr(
        chatgpt,
        "account_store",
        lambda *args: {
            "active": "synthetic",
            "accounts": {
                "synthetic": {"access_token": "FAKE", "scopes": ["chatgpt.tokens.use.direct"]}
            },
        },
    )
    with Session(engine) as db:
        for provider in providers.ensure_providers(db):
            if provider.provider == "chatgpt":
                provider.enabled = True
        owner = db.scalar(select(Owner))
        owner.settings = {"cloud_fallback": False}
        db.commit()
    dashboard = next(
        row
        for row in signed_in.get("/api/v1/dashboard").json()["providers"]
        if row["provider"] == "chatgpt"
    )
    settings = next(
        row
        for row in signed_in.get("/api/v1/settings/providers").json()["providers"]
        if row["provider"] == "chatgpt"
    )
    assert dashboard["connected"] == any(account["connected"] for account in settings["accounts"])
    assert "accounts" not in dashboard
    assert dashboard["state"] == settings["state"]
    assert not dashboard["processing_allowed"]


def test_auto_image_upload_is_card_and_explicit_other_is_preserved(signed_in):
    event = expo(signed_in)
    _, saved = upload(signed_in, event)
    assert saved["document"]["type"] == "card"
    import hashlib

    from tests.test_library import fake_image

    content = fake_image()
    batch = signed_in.post("/api/v1/upload-sessions", json={"expo_id": event}).json()
    other = signed_in.post(
        f"/api/v1/upload-sessions/{batch['id']}/files",
        files={"file": ("other.jpg", content, "image/jpeg")},
        data={"kind": "other", "sha256": hashlib.sha256(content).hexdigest()},
    )
    assert other.status_code == 201 and other.json()["document"]["type"] == "other"


def test_backup_without_finished_time_never_claims_current(signed_in, engine):
    from app.db.operations import Backup
    from app.domain.backups import status

    with Session(engine) as db:
        db.add(Backup(trigger="synthetic", state="complete"))
        db.commit()
        result = status(db)
        assert result["warning"] and result["last_success"] is None
