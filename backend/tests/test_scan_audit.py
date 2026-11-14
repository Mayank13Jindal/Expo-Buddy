from io import BytesIO
from uuid import UUID

import numpy as np
from PIL import Image, ImageDraw
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.library import Document, DocumentPage
from app.db.processing import AssetDerivative
from app.pipeline.card_image import crop_card
from app.pipeline.prepare import prepare_document
from tests.test_library import expo, upload


def high_resolution_card():
    image = Image.new("RGB", (5000, 3500), "#202020")
    draw = ImageDraw.Draw(image)
    draw.polygon([(350, 550), (4600, 400), (4650, 2950), (400, 3100)], fill="white")
    draw.text((700, 900), "FICTIONAL LOGO", fill="red", font_size=170)
    draw.text((700, 1600), "person@example.invalid", fill="black", font_size=40)
    return image


def test_crop_preserves_detail_and_geometry_for_rebuild():
    image = high_resolution_card()
    cropped, info = crop_card(image)
    assert info["applied"]
    assert cropped.width > 2200, "Detection resolution must not become OCR resolution"
    assert info["space"] == "normalized_original" and len(info["output_size"]) == 2


def test_large_logo_rectangle_does_not_crop_out_contact_print():
    image = Image.new("RGB", (1600, 1000), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((150, 100, 1450, 700), fill="#333333")
    draw.text((180, 820), "person@example.invalid +1 202 555 0123", fill="black", font_size=38)
    cropped, info = crop_card(image)
    assert not info["applied"] and cropped.size == image.size


def test_ocr_derivative_is_lossless_and_manual_crop_uses_displayed_base(
    signed_in, engine, settings
):
    buffer = BytesIO()
    high_resolution_card().save(buffer, format="PNG")
    _, saved = upload(signed_in, expo(signed_in), buffer.getvalue())
    id = UUID(saved["document"]["id"])
    with Session(engine) as db:
        doc = db.get(Document, id)
        prepare_document(db, doc, settings)
        db.commit()
        page = db.scalar(select(DocumentPage).where(DocumentPage.document_id == id))
        ocr = db.scalar(
            select(AssetDerivative).where(
                AssetDerivative.document_page_id == page.id, AssetDerivative.kind == "ocr"
            )
        )
        with Image.open(settings.previews_dir / ocr.path) as image:
            before = image.copy()
            assert image.format == "PNG"
        response = signed_in.post(
            f"/api/v1/documents/{id}/crop",
            json={"page_id": str(page.id), "left": 0.1, "top": 0.1, "right": 0.9, "bottom": 0.9},
        )
        assert response.status_code == 200, response.text
        db.expire_all()
        doc = db.get(Document, id)
        prepare_document(db, doc, settings)
        db.commit()
        actual = db.scalar(
            select(AssetDerivative).where(
                AssetDerivative.document_page_id == page.id,
                AssetDerivative.kind == "ocr",
                AssetDerivative.revision == doc.revision,
            )
        )
        with Image.open(settings.previews_dir / actual.path) as image:
            expected = before.crop(
                (
                    round(0.1 * before.width),
                    round(0.1 * before.height),
                    round(0.9 * before.width),
                    round(0.9 * before.height),
                )
            )
            assert image.size == expected.size
            assert np.array_equal(np.asarray(image), np.asarray(expected)), (
                "Manual crop must use the displayed auto-cropped card"
            )


def test_reprocess_without_options_keeps_capture_instructions(signed_in):
    _, saved = upload(signed_in, expo(signed_in))
    id = saved["document"]["id"]
    signed_in.post(
        f"/api/v1/documents/{id}/reprocess",
        json={"instructions": "Check the logo spelling", "auto_crop": False, "image_check": True},
    )
    response = signed_in.post(f"/api/v1/documents/{id}/reprocess", json={})
    assert response.status_code == 200
    assert response.json()["processing_options"]["instructions"] == "Check the logo spelling"
    assert response.json()["processing_options"]["auto_crop"] is False
    assert response.json()["processing_options"]["image_check"] is True


def test_blank_ocr_results_are_not_presented_as_a_successful_ai_scan(signed_in, engine, settings):
    from app.db.processing import ExtractionRun, OCRResult
    from app.pipeline.ai import extract_document

    _, saved = upload(signed_in, expo(signed_in))
    id = UUID(saved["document"]["id"])
    with Session(engine) as db:
        doc = db.get(Document, id)
        page = db.scalar(select(DocumentPage).where(DocumentPage.document_id == id))
        run = ExtractionRun(
            document_id=id, stage="ocr", provider="local", input_revision=1, status="succeeded"
        )
        db.add(run)
        db.flush()
        db.add(
            OCRResult(
                document_page_id=page.id,
                extraction_run_id=run.id,
                revision=1,
                text="",
                raw={"lines": []},
                engine_version="fake",
            )
        )
        db.commit()
        extract_document(db, doc, settings)
        assert doc.processing_state == "needs_review"


def test_image_check_is_queued_independently_before_text_ai(
    signed_in, engine, settings, monkeypatch
):
    from app.db.processing import Job
    from app.pipeline.ocr import read_document

    monkeypatch.setattr("app.pipeline.ocr.read_image", lambda *args: ("", {"lines": []}))
    _, saved = upload(signed_in, expo(signed_in))
    id = UUID(saved["document"]["id"])
    with Session(engine) as db:
        doc = db.get(Document, id)
        doc.group_state = "confirmed"
        doc.processing_options = {"image_check": True}
        prepare_document(db, doc, settings)
        read_document(db, doc, settings)
        jobs = list(db.scalars(select(Job).where(Job.target_id == id).order_by(Job.created_at)))
        assert [job.kind for job in jobs if job.pool == "ai"] == ["vision", "ai"]


def test_vision_partial_reading_does_not_require_repeating_every_printed_email():
    from app.domain.providers import decode_extraction

    value = decode_extraction(
        '{"company_name": null}', "Printed mail: info@example.invalid", require_complete=False
    )
    assert value.company_name is None


def test_new_prepared_revision_is_visible_without_reloading_document(signed_in, engine, settings):
    _, saved = upload(signed_in, expo(signed_in))
    id = UUID(saved["document"]["id"])
    with Session(engine) as db:
        prepare_document(db, db.get(Document, id), settings)
        db.commit()
    before = signed_in.get(f"/api/v1/documents/{id}").json()["pages"][0]["preview_revision"]
    signed_in.post(f"/api/v1/documents/{id}/reprocess", json={})
    assert signed_in.get(f"/api/v1/documents/{id}").json()["pages"][0]["preview_revision"] == before
    with Session(engine) as db:
        prepare_document(db, db.get(Document, id), settings)
        db.commit()
    assert (
        signed_in.get(f"/api/v1/documents/{id}").json()["pages"][0]["preview_revision"]
        == before + 1
    )
