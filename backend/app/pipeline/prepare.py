import os
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.storage import StorageGuard, configured_volumes
from app.db.library import Asset, Document, DocumentPage
from app.db.processing import AssetDerivative
from app.domain.uploads import asset_path


def render_page(asset: Asset, page: DocumentPage, settings: Settings) -> Image.Image:
    path = asset_path(settings.assets_dir, asset.storage_path)
    if asset.mime == "application/pdf":
        import pypdfium2 as pdfium

        with pdfium.PdfDocument(path) as pdf:
            pdf_page = pdf[(page.pdf_page_no or 1) - 1]
            try:
                width, height = pdf_page.get_size()
                scale = min(3.0, 4096 / max(width, height))
                bitmap = pdf_page.render(scale=scale)
                try:
                    return bitmap.to_pil().convert("RGB")
                finally:
                    bitmap.close()
            finally:
                pdf_page.close()
    with Image.open(path) as image:
        image.draft("RGB", (6000, 6000))
        ImageOps.exif_transpose(image, in_place=True)
        image.thumbnail((6000, 6000), reducing_gap=3)
        return image.convert("RGB")


def save_webp(image: Image.Image, destination: Path, size: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    temporary = destination.with_name(f".{uuid4()}{destination.suffix}")
    try:
        copy = image.copy()
        copy.thumbnail((size, size))
        copy.save(temporary, format="PNG") if destination.suffix == ".png" else copy.save(
            temporary, format="WEBP", quality=88
        )
        copy.close()
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_document(db: Session, document: Document, settings: Settings) -> None:
    import imagehash

    for page in db.scalars(
        select(DocumentPage)
        .where(DocumentPage.document_id == document.id)
        .order_by(DocumentPage.order)
    ):
        StorageGuard(configured_volumes(settings)).require_ready()
        asset = db.get(Asset, page.asset_id)
        with render_page(asset, page, settings) as original:
            image = original.copy()
            if asset.perceptual_hash is None:
                asset.perceptual_hash = str(imagehash.phash(original))
            transform = db.scalar(
                select(AssetDerivative)
                .where(
                    AssetDerivative.document_page_id == page.id,
                    AssetDerivative.kind == "transform",
                    AssetDerivative.revision <= document.revision,
                )
                .order_by(AssetDerivative.revision.desc())
                .limit(1)
            )
            if transform and transform.params.get("base_preparation"):
                from app.pipeline.card_image import apply_card_crop

                image.close()
                image = apply_card_crop(original, transform.params["base_preparation"])
            for operation in transform.params.get("operations", []) if transform else []:
                previous = image
                if operation["kind"] == "rotate":
                    image = image.rotate(-operation["degrees"], expand=True)
                elif operation["kind"] == "crop":
                    image = image.crop(
                        (
                            round(operation["left"] * image.width),
                            round(operation["top"] * image.height),
                            round(operation["right"] * image.width),
                            round(operation["bottom"] * image.height),
                        )
                    )
                if image is not previous:
                    previous.close()
            preparation = {
                "applied": False,
                "reason": "Manual transform or automatic crop disabled.",
            }
            if (
                (not transform or transform.params.get("auto_base_pending"))
                and document.processing_options.get("auto_crop", True)
                and asset.mime != "application/pdf"
            ):
                from app.pipeline.card_image import crop_card

                cropped, preparation = crop_card(image)
                image.close()
                image = cropped
            for kind, size in (("thumbnail", 320), ("preview", 1600), ("ocr", 4096)):
                existing = db.scalar(
                    select(AssetDerivative).where(
                        AssetDerivative.document_page_id == page.id,
                        AssetDerivative.kind == kind,
                        AssetDerivative.revision == document.revision,
                    )
                )
                extension = "png" if kind == "ocr" else "webp"
                relative = f"{asset.id}/{page.id}/r{document.revision}/{kind}.{extension}"
                save_webp(image, settings.previews_dir / relative, size)
                if existing:
                    existing.path = relative
                    existing.params = {"size": size, "oriented": True, "auto_crop": preparation}
                else:
                    db.add(
                        AssetDerivative(
                            asset_id=asset.id,
                            document_page_id=page.id,
                            kind=kind,
                            revision=document.revision,
                            path=relative,
                            params={"size": size, "oriented": True, "auto_crop": preparation},
                        )
                    )
    db.flush()
