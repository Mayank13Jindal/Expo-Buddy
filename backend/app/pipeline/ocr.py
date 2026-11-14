from functools import lru_cache
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.library import Asset, Document, DocumentPage
from app.db.processing import AssetDerivative, ExtractionRun, OCRResult
from app.domain.jobs import WaitForResource
from app.domain.uploads import asset_path
from app.pipeline.index import index_text

DETECTION = "PP-OCRv5_mobile_det-0d63e78e2b68"
RECOGNITION = "en_PP-OCRv5_mobile_rec-267c36e24c33"
ENGINE_VERSION = "PaddleOCR 3.7.0 / PP-OCRv5 English / 0d63e78e2b68+267c36e24c33 / prep2"


@lru_cache(maxsize=1)
def engine(models_dir: Path):
    detection, recognition = models_dir / "ocr" / DETECTION, models_dir / "ocr" / RECOGNITION
    if not all((path / "inference.pdiparams").is_file() for path in (detection, recognition)):
        raise WaitForResource(
            "Reading paused: download the local OCR models from Settings or make models."
        )
    from paddleocr import PaddleOCR

    return PaddleOCR(
        text_detection_model_name="PP-OCRv5_mobile_det",
        text_detection_model_dir=str(detection),
        text_recognition_model_name="en_PP-OCRv5_mobile_rec",
        text_recognition_model_dir=str(recognition),
        device="cpu",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        enable_mkldnn=False,
        cpu_threads=2,
        text_det_limit_side_len=1536,
        text_det_limit_type="max",
    )


def embedded_text(path: Path, page_number: int) -> str | None:
    try:
        text = PdfReader(path).pages[page_number - 1].extract_text() or ""
        usable = sum(char.isalnum() for char in text)
        return text if usable >= 20 and usable / max(1, len(text)) > 0.35 else None
    except Exception:
        return None


def predict_lines(image, models_dir):
    import numpy as np

    # PaddleX OCR's ReadImage(format="BGR") expects OpenCV channel order for arrays.
    results = list(engine(models_dir).predict(np.asarray(image.convert("RGB"))[:, :, ::-1].copy()))
    if not results:
        return []
    raw = results[0].json
    values = raw.get("res", raw)
    boxes = values.get("rec_polys", values.get("dt_polys", []))
    return [
        {
            "text": text,
            "score": float(score),
            "box": [[float(x), float(y)] for x, y in (boxes[i] if i < len(boxes) else [])],
        }
        for i, (text, score) in enumerate(
            zip(values.get("rec_texts", []), values.get("rec_scores", []), strict=True)
        )
    ]


def line_quality(lines):
    score, horizontal, count = 0.0, 0.0, 0.0
    for line in lines:
        weight = min(100, sum(char.isalnum() for char in line["text"]))
        box = line["box"]
        upright = not box or max(x for x, y in box) - min(x for x, y in box) >= 1.2 * (
            max(y for x, y in box) - min(y for x, y in box)
        )
        score += weight * line["score"] ** 3 * (1.0 if upright else 0.25)
        horizontal += weight * upright
        count += weight
    return score, horizontal / max(1, count)


def merge_lines(lines, extra):
    ambiguities = []
    for incoming in extra:
        if not incoming["box"]:
            continue
        ix, iy = zip(*incoming["box"], strict=False)
        matched = None
        for i, old in enumerate(lines):
            if not old["box"]:
                continue
            ox, oy = zip(*old["box"], strict=False)
            overlap = max(0, min(max(ix), max(ox)) - max(min(ix), min(ox))) * max(
                0, min(max(iy), max(oy)) - max(min(iy), min(oy))
            )
            minimum = min(
                (max(ix) - min(ix)) * (max(iy) - min(iy)), (max(ox) - min(ox)) * (max(oy) - min(oy))
            )
            if overlap / max(1, minimum) > 0.65:
                matched = i
                if old["text"].casefold() != incoming["text"].casefold():
                    if any(char in old["text"] + incoming["text"] for char in "@0123456789"):
                        ambiguities.append({"first": old["text"], "alternative": incoming["text"]})
                if old["text"].casefold() in incoming["text"].casefold() and len(
                    incoming["text"]
                ) > len(old["text"]):
                    lines[i] = incoming
                elif (
                    incoming["text"].casefold() not in old["text"].casefold()
                    and incoming["score"] > old["score"] + 0.03
                ):
                    lines[i] = incoming
                break
        if matched is None:
            lines.append(incoming)
    return ambiguities


def read_image(path: Path, models_dir: Path) -> tuple[str, dict]:
    from statistics import median

    from PIL import Image, ImageFilter, ImageOps

    with Image.open(path) as source:
        original = source.convert("RGB")
    width, height = original.size
    best, best_score, rotation = [], -1.0, 0
    for degrees in (0, 90, 270, 180):
        with original.rotate(-degrees, expand=True) as candidate:
            lines = predict_lines(candidate, models_dir)
        quality, horizontal = line_quality(lines)
        if quality > best_score:
            best, best_score, rotation = lines, quality, degrees
        if (
            degrees == 0
            and lines
            and min(line["score"] for line in lines) > 0.96
            and quality > 60
            and horizontal > 0.9
        ):
            break
    ambiguities, passes = [], ["orientation"]
    with original.rotate(-rotation, expand=True) as oriented:
        if not best or any(line["score"] < 0.85 for line in best):
            enhanced = ImageOps.autocontrast(oriented, cutoff=1).filter(
                ImageFilter.UnsharpMask(radius=1.2, percent=120, threshold=3)
            )
            extra = predict_lines(enhanced, models_dir)
            ambiguities += merge_lines(best, extra)
            enhanced.close()
            passes.append("contrast")
        heights = [
            max(y for x, y in line["box"]) - min(y for x, y in line["box"])
            for line in best
            if line["box"]
        ]
        if max(oriented.size) > 2600 and (not heights or median(heights) < 32):
            tw, th = round(oriented.width * 0.6), round(oriented.height * 0.6)
            for x, y in [
                (0, 0),
                (oriented.width - tw, 0),
                (0, oriented.height - th),
                (oriented.width - tw, oriented.height - th),
            ]:
                with oriented.crop((x, y, x + tw, y + th)) as tile:
                    extra = predict_lines(tile, models_dir)
                for line in extra:
                    line["box"] = [[px + x, py + y] for px, py in line["box"]]
                ambiguities += merge_lines(best, extra)
            passes.append("fine_print_tiles")

    # Sort before mapping back; vertical OCR can recognize words yet scramble name/title order.
    def reading_key(line):
        box = line["box"]
        return (min((y for x, y in box), default=0), min((x for x, y in box), default=0))

    best.sort(key=reading_key)

    def undo(x, y):
        if rotation == 90:
            return [y, height - x]
        if rotation == 180:
            return [width - x, height - y]
        if rotation == 270:
            return [width - y, x]
        return [x, y]

    for line in best:
        line["box"] = [
            [max(0, min(width, x)), max(0, min(height, y))]
            for x, y in [undo(*point) for point in line["box"]]
        ]
    original.close()
    return "\n".join(line["text"] for line in best), {
        "lines": best,
        "engine": ENGINE_VERSION,
        "image_width": width,
        "image_height": height,
        "reading_rotation": rotation,
        "passes": passes,
        "ambiguities": ambiguities[:20],
    }


def read_document(db: Session, document: Document, settings: Settings) -> None:
    run = db.scalar(
        select(ExtractionRun)
        .where(
            ExtractionRun.document_id == document.id,
            ExtractionRun.stage == "ocr",
            ExtractionRun.input_revision == document.revision,
            ExtractionRun.status == "running",
        )
        .order_by(ExtractionRun.created_at.desc())
        .limit(1)
    ) or ExtractionRun(
        document_id=document.id,
        stage="ocr",
        provider="local",
        model="PP-OCRv5 English",
        version=ENGINE_VERSION,
        input_revision=document.revision,
        status="running",
    )
    db.add(run)
    db.flush()
    reasons = list(document.review_reasons)
    for page in db.scalars(
        select(DocumentPage)
        .where(DocumentPage.document_id == document.id)
        .order_by(DocumentPage.order)
    ):
        existing = db.scalar(
            select(OCRResult).where(
                OCRResult.document_page_id == page.id, OCRResult.revision == document.revision
            )
        )
        if existing:
            continue
        asset = db.get(Asset, page.asset_id)
        derivative = db.scalar(
            select(AssetDerivative).where(
                AssetDerivative.document_page_id == page.id,
                AssetDerivative.kind == "ocr",
                AssetDerivative.revision == document.revision,
            )
        )
        transformed = db.scalar(
            select(AssetDerivative.id)
            .where(
                AssetDerivative.document_page_id == page.id,
                AssetDerivative.kind == "transform",
                AssetDerivative.revision <= document.revision,
            )
            .limit(1)
        )
        text = (
            embedded_text(asset_path(settings.assets_dir, asset.storage_path), page.pdf_page_no)
            if page.pdf_page_no and not transformed
            else None
        )
        if text:
            raw = {"source": "embedded_pdf_text", "lines": []}
            version = "pypdf 6.21.3"
        else:
            if not derivative:
                raise RuntimeError("Preview is not ready")
            text, raw = read_image(settings.previews_dir / derivative.path, settings.models_dir)
            version = ENGINE_VERSION
            if any(line["score"] < 0.8 for line in raw["lines"]):
                reasons.append(f"Page {page.order + 1}: some printed text is unclear.")
            if raw.get("ambiguities"):
                reasons.append(
                    f"Page {page.order + 1}: OCR readings disagree on contact characters; compare O/0, e/c and digits with the photo."
                )
            if not text.strip():
                reasons.append(f"Page {page.order + 1}: no readable text found.")
        raw["asset_id"] = str(asset.id)
        db.add(
            OCRResult(
                document_page_id=page.id,
                extraction_run_id=run.id,
                revision=document.revision,
                text=text,
                raw=raw,
                engine_version=version,
            )
        )
        index_text(db, "page", page.id, text, document.revision, document=document, page_id=page.id)
    run.status = "succeeded"
    document.review_reasons = list(dict.fromkeys(reasons))
    if reasons:
        document.review_state = "needs_attention"
    document.processing_state = (
        "waiting_ai" if document.group_state == "confirmed" else "waiting_grouping"
    )
    if document.group_state == "confirmed":
        from app.domain.jobs import enqueue

        if document.processing_options.get("image_check"):
            enqueue(db, "vision", document.id, document.revision, pool="ai")
        enqueue(db, "ai", document.id, document.revision, pool="ai")
    db.flush()
