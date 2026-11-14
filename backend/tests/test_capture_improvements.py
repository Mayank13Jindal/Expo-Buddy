import hashlib
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.intelligence import Company, Contact
from app.db.library import Document, DocumentPage, Note
from app.db.processing import ExtractionRun
from app.domain.providers import decode_extraction
from app.pipeline.ai import apply_extraction, verified
from app.pipeline.card_image import crop_card
from app.pipeline.ocr import read_image
from app.providers.schema import Evidence, extraction_schema
from tests.test_library import expo, upload


def test_password_minimum_is_eight_and_change_uses_same_rule(client):
    assert client.post("/api/v1/auth/setup", json={"password": "seven77"}).status_code == 422
    assert client.post("/api/v1/auth/setup", json={"password": "eight888"}).status_code == 201
    client.headers["X-CSRF-Token"] = client.cookies["expo_csrf"]
    assert (
        client.post(
            "/api/v1/auth/password", json={"current_password": "eight888", "password": "new88888"}
        ).status_code
        == 200
    )
    assert client.post("/api/v1/auth/login", json={"password": "new88888"}).status_code == 200


def test_capture_context_is_durable_idempotent_and_autostarts(
    signed_in, engine, settings, monkeypatch
):
    from app.pipeline.ocr import read_document
    from app.pipeline.prepare import prepare_document

    event = expo(signed_in)
    session = signed_in.post("/api/v1/upload-sessions", json={"expo_id": event}).json()["id"]
    stream = BytesIO()
    Image.new("RGB", (600, 350), "white").save(stream, format="PNG")
    data = stream.getvalue()
    form = {"instructions": "Fictional owner context: check the logo", "auto_process": "true"}
    response = signed_in.post(
        f"/api/v1/upload-sessions/{session}/files",
        data=form,
        files={"file": ("fake.png", data, "image/png")},
    )
    assert response.status_code == 201, response.text
    saved = response.json()
    docid = UUID(saved["document"]["id"])
    again = signed_in.post(
        f"/api/v1/upload-sessions/{session}/files",
        data={**form, "sha256": saved["asset"]["sha256"]},
    )
    assert again.json()["document"]["id"] == str(docid)
    monkeypatch.setattr(
        "app.pipeline.ocr.read_image", lambda *args: ("FICTIONAL PRINTED COMPANY", {"lines": []})
    )
    with Session(engine) as db:
        doc = db.get(Document, docid)
        assert doc.group_state == "confirmed"
        assert doc.processing_options["instructions"] == form["instructions"]
        assert db.scalar(select(func.count(Note.id))) == 1
        prepare_document(db, doc, settings)
        read_document(db, doc, settings)
        assert doc.group_state == "confirmed" and doc.processing_state == "waiting_ai"
        db.commit()
    assert (
        hashlib.sha256(
            signed_in.get("/api/v1/assets/" + saved["asset"]["id"] + "/original").content
        ).hexdigest()
        == saved["asset"]["sha256"]
    )
    assert (
        signed_in.post(
            f"/api/v1/documents/{docid}/reprocess",
            json={"instructions": "Check O versus zero", "auto_crop": False},
        ).status_code
        == 200
    )
    assert (
        signed_in.get(f"/api/v1/documents/{docid}").json()["processing_options"]["instructions"]
        == "Check O versus zero"
    )


def test_auto_crop_straightens_one_card_and_keeps_original():
    source = Image.new("RGB", (1000, 800), "#18251e")
    draw = ImageDraw.Draw(source)
    draw.polygon([(100, 180), (880, 120), (900, 590), (120, 650)], fill="white")
    draw.text((240, 300), "FICTIONAL SAMPLE COMPANY", fill="black", font_size=35)
    before = source.tobytes()
    cropped, info = crop_card(source)
    assert info["applied"] and cropped.width > cropped.height
    assert cropped.height < source.height and cropped.width < source.width
    assert before == source.tobytes()
    blank = Image.new("RGB", (600, 350), "white")
    copy, info = crop_card(blank)
    assert not info["applied"] and copy.size == blank.size


def test_orientation_chooses_readable_view_without_mutating_source(tmp_path, monkeypatch):
    path = tmp_path / "sideways.png"
    image = Image.new("RGB", (200, 400), "black")
    ImageDraw.Draw(image).rectangle((0, 380, 20, 399), fill="red")
    image.save(path)
    before = path.read_bytes()

    class Fake:
        def predict(self, array):
            correct = array[0, 0, 2] > 200
            return [
                SimpleNamespace(
                    json={
                        "res": {
                            "rec_texts": ["FICTIONAL PRINTED NAME"],
                            "rec_scores": [0.99 if correct else 0.2],
                            "rec_polys": [[[5, 5], [50, 5], [50, 20], [5, 20]]],
                        }
                    }
                )
            ]

    monkeypatch.setattr("app.pipeline.ocr.engine", lambda folder: Fake())
    text, raw = read_image(path, tmp_path)
    assert raw["reading_rotation"] == 90 and "PRINTED NAME" in text
    assert all(0 <= x <= 200 and 0 <= y <= 400 for line in raw["lines"] for x, y in line["box"])
    assert path.read_bytes() == before


def test_short_labels_and_literal_character_evidence(signed_in, engine):
    import json

    _, saved = upload(signed_in, expo(signed_in))
    docid = UUID(saved["document"]["id"])
    with Session(engine) as db:
        page = db.scalar(select(DocumentPage).where(DocumentPage.document_id == docid))
        text = f"Page P1 [{page.id}]\nFICTIONAL EAPRO\nSr. Manager\n"
        raw = {
            "company_name": {
                "value": "FICTIONAL EAPRO",
                "evidence": {"page_id": "P1", "quote": "FICTIONAL EAPRO"},
            },
            "people": [
                {
                    "full_name": {
                        "value": "Sr. Manager",
                        "evidence": {"page_id": "P1", "quote": "Sr. Manager"},
                    }
                }
            ],
        }
        value = decode_extraction(json.dumps(raw), text)
        assert value.company_name.evidence.page_id == page.id
        run = ExtractionRun(
            document_id=docid, stage="ai", provider="fake", status="succeeded", input_revision=1
        )
        db.add(run)
        db.flush()
        apply_extraction(db, db.get(Document, docid), value, {str(page.id): text}, run)
        db.commit()
        assert db.scalar(select(func.count(Contact.id))) == 0
        assert not verified(
            "EAPR0", Evidence(page_id=page.id, quote="EAPRO"), {str(page.id): "EAPRO"}
        )
        assert verified(
            "12 Main Road",
            Evidence(page_id=page.id, quote="12 Main Road"),
            {str(page.id): "12 Main Other Column Text Road"},
            interleaved=True,
        )
    schema = extraction_schema()
    assert set(schema["required"]) == set(schema["properties"])
    assert "format" not in schema["$defs"]["Evidence"]["properties"]["page_id"]


def test_checked_examples_measure_raw_ai_not_corrected_records(signed_in, engine):
    _, saved = upload(signed_in, expo(signed_in))
    id = saved["document"]["id"]
    company = signed_in.post(
        "/api/v1/companies", json={"fields": {"display_name": "Corrected Fictional Company"}}
    ).json()["id"]
    signed_in.post(f"/api/v1/documents/{id}/attach-company", json={"company_id": company})
    assert (
        signed_in.post(
            f"/api/v1/accuracy/examples/{id}",
            json={"confirmed": True, "checked_fields": ["company_name"]},
        ).status_code
        == 422
    )
    signed_in.patch(f"/api/v1/documents/{id}", json={"review_state": "reviewed"})
    assert (
        signed_in.post(
            f"/api/v1/accuracy/examples/{id}",
            json={"confirmed": True, "checked_fields": ["company_name"]},
        ).status_code
        == 200
    )
    with Session(engine) as db:
        db.add(
            ExtractionRun(
                document_id=UUID(id),
                stage="ai",
                provider="fake",
                model="pinned-fake",
                status="succeeded",
                input_revision=1,
                output={"data": {"company_name": {"value": "Wrong OCR Company"}}},
            )
        )
        db.commit()
    result = signed_in.get("/api/v1/accuracy").json()
    assert result["exact_match_percent"] == 0 and result["measured_field_groups"] == 1
    assert result["examples"][0]["model"] == "pinned-fake"


def test_requested_image_check_never_sends_images_to_remote_ollama(
    signed_in, engine, settings, monkeypatch
):
    from app.domain.providers import ensure_providers
    from app.pipeline.vision import image_check

    _, saved = upload(signed_in, expo(signed_in))
    id = UUID(saved["document"]["id"])

    class Remote:
        def inspect_model(self):
            return {"remote": True, "model_digest": "fake"}

        def extract(self, *args, **kwargs):
            raise AssertionError("Images must not leave through remote Ollama")

    monkeypatch.setattr("app.pipeline.vision.providers.adapter", lambda *args: Remote())
    with Session(engine) as db:
        provider = ensure_providers(db)[0]
        provider.enabled = True
        db.commit()
        doc = db.get(Document, id)
        doc.group_state = "confirmed"
        image_check(db, doc, settings, {"00000000-0000-0000-0000-000000000000": "fictional OCR"})
        db.commit()
        assert doc.review_state == "needs_attention"
        assert any("local Ollama" in reason for reason in doc.review_reasons)
        run = db.scalar(select(ExtractionRun).where(ExtractionRun.stage == "vision"))
        assert run.status == "needs_review" and not doc.company_id


@pytest.mark.parametrize("page_label", ["P1", "00000000-0000-0000-0000-000000000000"])
def test_local_image_check_creates_a_proposal_and_keeps_owner_value(
    signed_in, engine, settings, monkeypatch, page_label
):
    import json

    import httpx

    from app.db.intelligence import Proposal
    from app.domain.providers import ensure_providers
    from app.pipeline.prepare import prepare_document
    from app.pipeline.vision import image_check
    from app.providers.base import ProviderReply

    _, saved = upload(signed_in, expo(signed_in))
    id = UUID(saved["document"]["id"])
    company = signed_in.post(
        "/api/v1/companies", json={"fields": {"display_name": "Owner checked logo"}}
    ).json()["id"]
    signed_in.post(f"/api/v1/documents/{id}/attach-company", json={"company_id": company})

    class Vision:
        base_url = "http://127.0.0.1:11434"
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"capabilities": ["vision"]})
            )
        )

        def inspect_model(self):
            return {"remote": False, "model_digest": "fictional-version"}

        def extract(self, text, **kwargs):
            assert len(kwargs["images"]) == 1 and len(kwargs["images"][0]) > 30
            return ProviderReply(
                json.dumps(
                    {
                        "company_name": {
                            "value": "Suggested image logo",
                            "evidence": {"page_id": page_label, "quote": "Suggested image logo"},
                        }
                    }
                )
            )

    monkeypatch.setattr("app.pipeline.vision.providers.adapter", lambda *args: Vision())
    with Session(engine) as db:
        provider = ensure_providers(db)[0]
        provider.enabled = True
        db.commit()
        doc = db.get(Document, id)
        page = db.scalar(select(DocumentPage).where(DocumentPage.document_id == id))
        doc.group_state = "confirmed"
        prepare_document(db, doc, settings)
        image_check(db, doc, settings, {str(page.id): "Unclear company logo"})
        db.commit()
        proposal = db.scalar(select(Proposal).where(Proposal.actor == "image-check"))
        if page_label == "P1":
            assert proposal and proposal.proposed_value == "Suggested image logo"
        else:
            assert proposal is None
            assert any("unknown source page" in reason for reason in doc.review_reasons)
        assert db.get(Company, UUID(company)).display_name == "Owner checked logo"
        assert doc.review_state == "needs_attention"
