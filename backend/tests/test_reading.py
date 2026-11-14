import hashlib
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch
from uuid import UUID, uuid4

from PIL import Image, ImageDraw
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.library import Document, now
from app.db.processing import AssetDerivative, OCRResult
from app.domain.jobs import claim, enqueue, fail_or_retry
from app.pipeline.ocr import read_document
from app.pipeline.prepare import prepare_document
from tests.test_library import expo, upload


def test_pdf_embedded_and_scanned_pages(signed_in, engine, settings):
    pdf = BytesIO()
    writer = canvas.Canvas(pdf)
    writer.drawString(50, 700, "FICTIONAL SOLAR COMPANY makes mounting structures")
    writer.showPage()
    image = Image.new("RGB", (800, 400), "white")
    ImageDraw.Draw(image).text((30, 30), "FAKE scanned page", fill="black")
    from reportlab.lib.utils import ImageReader

    writer.drawImage(ImageReader(image), 30, 400, width=500, height=250)
    writer.showPage()
    writer.save()
    original = pdf.getvalue()
    _, result = upload(signed_in, expo(signed_in), original)
    with Session(engine) as db:
        doc = db.get(
            Document,
            result["document"]["id"]
            if False
            else __import__("uuid").UUID(result["document"]["id"]),
        )
        prepare_document(db, doc, settings)
        with patch(
            "app.pipeline.ocr.read_image",
            return_value=("Fictional scanned brochure", {"lines": []}),
        ) as ocr:
            read_document(db, doc, settings)
            assert ocr.call_count == 1
        db.commit()
        texts = list(db.scalars(select(OCRResult).order_by(OCRResult.created_at)))
        assert "mounting structures" in texts[0].text
        assert texts[0].engine_version == "pypdf 6.21.3"
        assert len(texts) == 2
    saved = signed_in.get(f"/api/v1/assets/{result['asset']['id']}/original").content
    assert hashlib.sha256(saved).digest() == hashlib.sha256(original).digest()
    assert signed_in.get("/api/v1/search?q=mounting").json()["results"]


def test_oriented_preview_keeps_original_and_repeated_prepare_is_idempotent(
    signed_in, engine, settings
):
    data = BytesIO()
    image = Image.new("RGB", (600, 350), "white")
    exif = image.getexif()
    exif[274] = 6
    image.save(data, format="JPEG", exif=exif)
    _, result = upload(signed_in, expo(signed_in), data.getvalue())

    with Session(engine) as db:
        doc = db.get(Document, UUID(result["document"]["id"]))
        prepare_document(db, doc, settings)
        prepare_document(db, doc, settings)
        db.commit()
        copies = list(db.scalars(select(AssetDerivative)))
        assert len(copies) == 3
        with Image.open(
            settings.previews_dir / next(copy.path for copy in copies if copy.kind == "preview")
        ) as preview:
            assert preview.height > preview.width
    assert (
        signed_in.get(f"/api/v1/assets/{result['asset']['id']}/original").content == data.getvalue()
    )


def test_leases_recover_and_retries_are_bounded(engine):
    target = uuid4()
    with Session(engine, expire_on_commit=False) as db:
        job = enqueue(db, "prepare", target, 1)
        assert enqueue(db, "prepare", target, 1).id == job.id
        db.commit()
        assert claim(db, "local", "first").id == job.id
        assert claim(db, "local", "second") is None
        job.lease_until = now() - timedelta(seconds=5)
        db.commit()
        recovered = claim(db, "local", "second")
        assert recovered.id == job.id and recovered.worker_id == "second"
        recovered.attempts = 5
        fail_or_retry(db, recovered, "Synthetic failure")
        assert recovered.state == "failed"
        assert claim(db, "local", "third") is None


def test_note_search_updates_and_delete_removes_match(signed_in):
    _, result = upload(signed_in, expo(signed_in))
    note = signed_in.post(
        "/api/v1/notes",
        json={"document_id": result["document"]["id"], "text": "fake unique zebra discovery"},
    ).json()
    assert signed_in.get("/api/v1/search?q=zebra").json()["results"][0]["source_type"] == "note"
    signed_in.patch(f"/api/v1/notes/{note['id']}", json={"text": "fake unique orchid discovery"})
    assert signed_in.get("/api/v1/search?q=zebra").json()["results"] == []
    assert signed_in.get("/api/v1/search?q=orchid").json()["results"]
    signed_in.delete(f"/api/v1/notes/{note['id']}")
    assert signed_in.get("/api/v1/search?q=orchid").json()["results"] == []


def test_sideways_ocr_uses_better_reading_and_maps_evidence_to_original(tmp_path):
    from app.pipeline.ocr import read_image

    source = tmp_path / 'sideways.png'
    image = Image.new('RGB', (100, 200), 'white')
    image.putpixel((0, 0), (255, 0, 0))
    image.save(source)
    before = hashlib.sha256(source.read_bytes()).hexdigest()

    def predict(image, models):
        if image.width == 200 and image.getpixel((199, 0)) == (255, 0, 0):
            return [{'text': 'FICTIONAL COMPANY', 'score': .99,
                     'box': [[10, 10], [180, 10], [180, 20], [10, 20]]}]
        if image.width == 200:
            return [{'text': 'garbled', 'score': .2,
                     'box': [[10, 10], [180, 10], [180, 20], [10, 20]]}]
        return [{'text': 'garbled company', 'score': .6,
                 'box': [[10, 10], [20, 10], [20, 180], [10, 180]]}]

    with patch('app.pipeline.ocr.predict_lines', side_effect=predict):
        text, raw = read_image(source, tmp_path)
    assert text == 'FICTIONAL COMPANY'
    assert raw['reading_rotation'] == 90
    assert raw['lines'][0]['box'] == [[10, 190], [10, 20], [20, 20], [20, 190]]
    assert (raw['image_width'], raw['image_height']) == (100, 200)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
