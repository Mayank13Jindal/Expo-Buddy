"""Review and export safety against disposable records, including legacy proposals."""

import io
from uuid import UUID, uuid4

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.intelligence import Company, Proposal
from app.db.library import Document
from app.domain import fields
from app.domain.contact_values import channel_issue, normalise_channel
from app.domain.review import changes
from tests.test_exports import generate
from tests.test_library import expo, upload


def review_record(web, engine):
    expo_id = expo(web)
    _, saved = upload(web, expo_id)
    doc_id = saved["document"]["id"]
    company = web.post(
        "/api/v1/companies",
        json={
            "fields": {
                "display_name": "FICTIONAL Review Company",
                "channels": [
                    {"kind": "phone", "raw": "+1 202 555 0101", "label": "Office"},
                    {"kind": "email", "raw": "kept@example.com", "label": "Work"},
                ],
            }
        },
    ).json()
    web.post(
        f"/api/v1/documents/{doc_id}/attach-company", json={"company_id": company["id"]}
    ).raise_for_status()
    with Session(engine) as db:
        doc = db.get(Document, UUID(doc_id))
        doc.processing_state = "ready"
        doc.review_state = "reviewed"
        row = db.get(Company, UUID(company["id"]))
        proposal = fields.proposal(
            db,
            "company",
            row.id,
            "channels",
            [
                {"kind": "phone", "raw": "+12025550101", "label": "Duplicate"},
                *row.channels[1:],
                {"kind": "email", "raw": "broken@@example.com"},
                {"kind": "email", "raw": "new@example.com"},
                {"kind": "address", "raw": "Possib1y Misspe1led Road"},
            ],
            reason="Synthetic OCR discrepancy",
            document_id=doc.id,
        )
        # Simulate a legacy record whose review flag was never set.
        doc.review_state = "reviewed"
        # Simulate an old no-op proposal, which must not inflate counts.
        db.add(
            Proposal(
                entity_type="company",
                entity_id=row.id,
                field="display_name",
                current_value=row.display_name,
                proposed_value=row.display_name,
                reason="Legacy no-op",
                document_id=doc.id,
            )
        )
        db.commit()
        proposal_id = str(proposal.id)
    return expo_id, doc_id, company["id"], proposal_id


def test_contact_identity_and_validation():
    assert normalise_channel("phone", "+1 (202) 555-0101") == normalise_channel(
        "phone", "0012025550101"
    )
    assert normalise_channel("email", "Person@EXAMPLE.COM") == "person@example.com"
    assert channel_issue({"kind": "email", "raw": "broken@@example.com"})
    assert channel_issue({"kind": "phone", "raw": "+123"})
    assert channel_issue({"kind": "web", "raw": "https://["})
    old = [{"kind": "phone", "raw": "+1 202 555 0101"}]
    assert not changes("channels", old, [{"kind": "phone", "raw": "+12025550101"}])
    assert not changes("display_name", " Same Name ", "same name")


def test_named_source_comparison_counts_status_and_partial_accept(signed_in, engine):
    expo_id, doc_id, company_id, proposal_id = review_record(signed_in, engine)
    data = signed_in.get(f"/api/v1/review?expo_id={expo_id}").json()
    assert len(data["documents"]) == 1 and len(data["proposals"]) == 1
    suggestion = data["proposals"][0]
    assert suggestion["record_name"] == "FICTIONAL Review Company"
    assert suggestion["source_page"]["asset"]["id"]
    assert suggestion["duplicate_warnings"]
    assert len(suggestion["changes"]) == 3
    invalid = next(
        change for change in suggestion["changes"] if change["after"] == "broken@@example.com"
    )
    valid = next(change for change in suggestion["changes"] if change["after"] == "new@example.com")
    assert not invalid["can_accept"]
    assert (
        signed_in.post(
            f"/api/v1/proposals/{proposal_id}/accept", json={"selected_changes": [invalid["index"]]}
        ).status_code
        == 422
    )
    assert (
        signed_in.post(
            f"/api/v1/proposals/{proposal_id}/accept", json={"selected_changes": [999]}
        ).status_code
        == 422
    )
    assert signed_in.post(f"/api/v1/review/{doc_id}/resolve", json={}).status_code == 409
    assert any(
        row["id"] == doc_id
        for row in signed_in.get("/api/v1/documents?review_state=needs_attention").json()
    )
    assert not any(
        row["id"] == doc_id
        for row in signed_in.get("/api/v1/documents?review_state=reviewed").json()
    )
    detail = signed_in.get(f"/api/v1/documents/{doc_id}").json()
    assert detail["review_status"] == "needs_attention"
    dashboard = signed_in.get("/api/v1/dashboard").json()
    assert dashboard["review"] == 1 and dashboard["proposed_changes"] == 1
    result = signed_in.post(
        f"/api/v1/proposals/{proposal_id}/accept", json={"selected_changes": [valid["index"]]}
    )
    assert result.status_code == 200, result.text
    assert result.json()["state"] == "partially_accepted"
    stored = signed_in.get(f"/api/v1/companies/{company_id}").json()["channels"]
    assert [item["raw"] for item in stored] == [
        "+1 202 555 0101",
        "kept@example.com",
        "new@example.com",
    ]
    assert signed_in.post(f"/api/v1/review/{doc_id}/resolve", json={}).status_code == 200
    assert not signed_in.get("/api/v1/review").json()["proposals"]


def test_stale_suggestion_cannot_overwrite_edit(signed_in, engine):
    _, _, company_id, proposal_id = review_record(signed_in, engine)
    signed_in.patch(
        f"/api/v1/companies/{company_id}",
        json={"fields": {"channels": [{"kind": "email", "raw": "owner@example.com"}]}},
    ).raise_for_status()
    assert (
        signed_in.post(
            f"/api/v1/proposals/{proposal_id}/accept", json={"selected_changes": [0]}
        ).status_code
        == 409
    )
    assert signed_in.post(f"/api/v1/proposals/{proposal_id}/reject", json={}).status_code == 200
    assert (
        signed_in.get(f"/api/v1/companies/{company_id}").json()["channels"][0]["raw"]
        == "owner@example.com"
    )


def test_flagged_export_requires_choice_and_download_carries_warning(signed_in, engine, settings):
    _, doc_id, _, _ = review_record(signed_in, engine)
    body = {
        "scope": "selected",
        "document_ids": [doc_id],
        "tables": ["companies"],
        "fields": {"companies": ["company_name", "emails"]},
        "format": "xlsx",
    }
    preview = signed_in.post("/api/v1/exports/preview", json=body).json()
    assert preview["counts"]["flagged_rows"] == 1
    assert preview["fields"]["companies"][-1] == "review_warning"
    assert "Unresolved" in preview["rows"]["companies"][0]["review_warning"]
    assert signed_in.post("/api/v1/exports", json=body).status_code == 409
    _, content = generate(signed_in, engine, settings, body)
    sheet = load_workbook(io.BytesIO(content))["Companies"]
    assert sheet["C1"].value == "Review warning" and "Unresolved" in sheet["C2"].value
    assert "broken@@" not in str(list(sheet.values))


def test_clean_reviewed_export_needs_no_override(signed_in, engine):
    _, saved = upload(signed_in, expo(signed_in))
    doc_id = saved["document"]["id"]
    signed_in.post(f"/api/v1/review/{doc_id}/resolve", json={}).raise_for_status()
    body = {
        "scope": "selected",
        "document_ids": [doc_id],
        "tables": ["documents"],
        "fields": {"documents": ["title"]},
        "format": "xlsx",
    }
    assert (
        signed_in.post("/api/v1/exports/preview", json=body).json()["counts"]["flagged_rows"] == 0
    )
    assert signed_in.post("/api/v1/exports", json=body).status_code == 202


def test_phone_reports_consolidate_and_only_pending_reports_are_shown(signed_in, engine):
    from app.db.capture import QueueReport

    client_id = str(uuid4())
    body = {
        "client_uuid": client_id,
        "device_label": "My phone",
        "files": 2,
        "notes": 0,
        "bytes": 30,
    }
    first = signed_in.post("/api/v1/sync/report", json=body)
    assert first.status_code == 200, first.text
    signed_in.post("/api/v1/sync/report", json={**body, "files": 3}).raise_for_status()
    signed_in.post(
        "/api/v1/sync/report", json={**body, "client_uuid": str(uuid4()), "files": 0}
    ).raise_for_status()
    reports = signed_in.get("/api/v1/dashboard").json()["phone_queue"]
    assert len(reports) == 1 and reports[0]["files"] == 3
    signed_in.delete(f"/api/v1/sync/report/{reports[0]['id']}").raise_for_status()
    assert not signed_in.get("/api/v1/dashboard").json()["phone_queue"]
    with Session(engine) as db:
        assert len(list(db.scalars(select(QueueReport)))) == 1
    # Dismissing a report does not prevent the real phone from reporting again.
    signed_in.post("/api/v1/sync/report", json=body).raise_for_status()
    assert len(signed_in.get("/api/v1/dashboard").json()["phone_queue"]) == 1


def test_extraction_holds_invalid_contact_and_address_before_storage(signed_in, engine):
    from app.db.library import DocumentPage
    from app.db.processing import ExtractionRun
    from app.pipeline.ai import apply_extraction
    from app.providers.schema import Extraction

    _, saved = upload(signed_in, expo(signed_in))
    with Session(engine) as db:
        doc = db.get(Document, UUID(saved["document"]["id"]))
        page = db.scalar(select(DocumentPage).where(DocumentPage.document_id == doc.id))
        printed = ["FICTIONAL Review Company", "broken@@example.com", "Possib1y Misspe1led Road"]

        def evidence(value):
            return {"page_id": str(page.id), "quote": value}

        data = {
            "company_name": {"value": printed[0], "evidence": evidence(printed[0])},
            "channels": [
                {"kind": kind, "raw": value, "evidence": evidence(value)}
                for kind, value in zip(("email", "address"), printed[1:], strict=True)
            ],
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
            db, doc, Extraction.model_validate(data), {str(page.id): "\n".join(printed)}, run
        )
        db.commit()
        assert not db.get(Company, doc.company_id).channels
        assert doc.review_state == "needs_attention"
        assert len(list(db.scalars(select(Proposal)))) == 1


def test_review_scope_excludes_other_expo(signed_in, engine):
    _, _, _, _ = review_record(signed_in, engine)
    other = expo(signed_in, name="OTHER SYNTHETIC EXPO")
    response = signed_in.get(f"/api/v1/review?expo_id={other}").json()
    assert not response["proposals"] and not response["documents"]


def test_bulk_review_undo_restores_uncertainty_reasons(signed_in, engine):
    _, saved = upload(signed_in, expo(signed_in))
    doc_id = saved["document"]["id"]
    with Session(engine) as db:
        doc = db.get(Document, UUID(doc_id))
        doc.review_state, doc.review_reasons = "needs_attention", ["Synthetic OCR uncertainty"]
        db.commit()
    result = signed_in.post("/api/v1/bulk", json={"action": "review", "document_ids": [doc_id]})
    assert result.status_code == 200, result.text
    assert not signed_in.get(f"/api/v1/documents/{doc_id}").json()["review_reasons"]
    signed_in.post(f"/api/v1/bulk/{result.json()['action_id']}/undo", json={}).raise_for_status()
    assert signed_in.get(f"/api/v1/documents/{doc_id}").json()["review_reasons"] == [
        "Synthetic OCR uncertainty"
    ]


def test_provider_input_contains_printed_text_and_explicit_context_not_private_notes(
    signed_in, engine, settings, monkeypatch
):
    from app.db.library import DocumentPage, Note
    from app.db.processing import ExtractionRun, OCRResult
    from app.domain import providers
    from app.pipeline.ai import extract_document
    from app.providers.schema import Extraction

    _, saved = upload(signed_in, expo(signed_in))
    captured = []

    def extract(db, config, text):
        captured.append(text)
        return Extraction(), {"provider": "synthetic", "model": "test", "version": "1"}

    monkeypatch.setattr(providers, "extract", extract)
    with Session(engine) as db:
        doc = db.get(Document, UUID(saved["document"]["id"]))
        doc.group_state = "confirmed"
        doc.processing_options = {"instructions": "EXPLICIT CAPTURE CONTEXT"}
        page = db.scalar(select(DocumentPage).where(DocumentPage.document_id == doc.id))
        db.add(Note(document_id=doc.id, text="PRIVATE PERSONAL ORCHID NOTE"))
        run = ExtractionRun(
            document_id=doc.id,
            stage="ocr",
            provider="synthetic",
            input_revision=1,
            status="succeeded",
        )
        db.add(run)
        db.flush()
        db.add(
            OCRResult(
                document_page_id=page.id,
                extraction_run_id=run.id,
                revision=doc.revision,
                text="FICTIONAL PRINTED CONTACT",
                engine_version="test",
            )
        )
        db.commit()
        extract_document(db, doc, settings)
    assert captured and "FICTIONAL PRINTED CONTACT" in captured[0]
    assert "EXPLICIT CAPTURE CONTEXT" in captured[0]
    assert "PRIVATE PERSONAL ORCHID NOTE" not in captured[0]


def test_image_checks_reject_cloud_backed_ollama_before_sending_images(
    signed_in, engine, settings, monkeypatch
):
    from types import SimpleNamespace

    from app.db.processing import ExtractionRun
    from app.domain import providers
    from app.pipeline.vision import image_check

    _, saved = upload(signed_in, expo(signed_in))
    monkeypatch.setattr(
        providers, "adapter", lambda *args: SimpleNamespace(inspect_model=lambda: {"remote": True})
    )
    with Session(engine) as db:
        row = providers.ensure_providers(db)[0]
        assert row.provider == "ollama"
        row.enabled = True
        doc = db.get(Document, UUID(saved["document"]["id"]))
        doc.group_state = "confirmed"
        db.commit()
        image_check(db, doc, settings, {})
        run = db.scalar(select(ExtractionRun).where(ExtractionRun.stage == "vision"))
        assert run.status == "needs_review" and "local Ollama" in run.error
