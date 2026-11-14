import hashlib
import os
import re
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from PIL import Image, UnidentifiedImageError
from pillow_heif import register_heif_opener
from pypdf import PdfReader
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.storage import StorageGuard
from app.db.library import Asset, Document, DocumentPage, Note, UploadSession
from app.domain.jobs import enqueue

register_heif_opener()
Image.MAX_IMAGE_PIXELS = 100_000_000
FORMATS = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
    "HEIF": ("image/heif", "heic"),
}


def safe_name(value: str) -> str:
    return (
        re.sub(r"[\x00-\x1f\x7f]", "", value.replace("\\", "/").split("/")[-1])[:250] or "Untitled"
    )


def asset_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise HTTPException(400, "Invalid file path.")
    return path


def inspect_file(path: Path, settings: Settings) -> dict:
    with path.open("rb") as stream:
        is_pdf = stream.read(5) == b"%PDF-"
    if is_pdf:
        if path.stat().st_size > settings.pdf_limit_bytes:
            raise HTTPException(413, "This PDF is too large. The limit is 400 MB.")
        try:
            reader = PdfReader(path)
            if reader.is_encrypted:
                raise HTTPException(422, "This PDF is password protected. Upload an unlocked copy.")
            count = len(reader.pages)
            if not count or count > settings.pdf_page_limit:
                raise HTTPException(422, f"PDFs can have up to {settings.pdf_page_limit} pages.")
            return {"mime": "application/pdf", "extension": "pdf", "page_count": count}
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, "This PDF could not be read. Try another copy.") from None
    if path.stat().st_size > settings.image_limit_bytes:
        raise HTTPException(413, "This image is too large. The limit is 100 MB.")
    try:
        with Image.open(path) as image:
            if image.format not in FORMATS:
                raise ValueError("Unsupported image")
            mime, extension = FORMATS[image.format]
            width, height = image.size
            image.verify()
        return {
            "mime": mime,
            "extension": extension,
            "page_count": 1,
            "width": width,
            "height": height,
        }
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(
            422, "Choose a JPEG, PNG, WebP, HEIC or PDF file that opens correctly."
        ) from None


def attach_asset(
    db: Session,
    upload: UploadSession,
    asset: Asset,
    client_uuid: UUID | None,
    type: str = "auto",
    options=None,
    filename: str = "",
) -> Document:
    key = str(client_uuid) if client_uuid else asset.sha256
    existing = db.scalar(
        select(Document).where(Document.upload_session_id == upload.id, Document.ingest_key == key)
    )
    if existing:
        return existing
    doc = Document(
        expo_id=upload.expo_id,
        upload_session_id=upload.id,
        ingest_key=key,
        title=safe_name(filename or asset.original_filename),
        type=("brochure" if asset.mime == "application/pdf" else "card")
        if type == "auto"
        else type,
        group_state="confirmed" if options and options.get("auto_process") else "suggested",
        processing_options=options or {},
    )
    db.add(doc)
    db.flush()
    for index in range(asset.page_count):
        db.add(
            DocumentPage(
                document_id=doc.id,
                asset_id=asset.id,
                order=index,
                pdf_page_no=index + 1 if asset.mime == "application/pdf" else None,
                role="front" if asset.page_count == 1 else "page",
            )
        )
    db.flush()
    if options and options.get("instructions"):
        note = Note(
            document_id=doc.id,
            text=options["instructions"],
            origin="capture-context",
            client_uuid=uuid5(NAMESPACE_URL, "expo-capture-note/" + str(doc.id)),
        )
        db.add(note)
        db.flush()
        from app.pipeline.index import index_text

        index_text(db, "note", note.id, note.text, 1, document=doc)
    enqueue(db, "prepare", doc.id, doc.revision)
    return doc


async def receive_file(
    db: Session,
    upload: UploadSession,
    file: UploadFile | None,
    expected_sha: str | None,
    client_uuid: UUID | None,
    kind: str,
    settings: Settings,
    guard: StorageGuard,
    options=None,
    filename: str = "",
) -> tuple[Asset, Document, bool]:
    guard.require_ready()
    if expected_sha and not re.fullmatch(r"[a-f0-9]{64}", expected_sha):
        raise HTTPException(422, "The file checksum is invalid.")
    if file is None:
        asset = (
            db.scalar(select(Asset).where(Asset.sha256 == expected_sha)) if expected_sha else None
        )
        if not asset or asset.purged_at:
            raise HTTPException(404, "The file is not saved yet. Upload it again.")
        if not asset_path(settings.assets_dir, asset.storage_path).is_file():
            raise HTTPException(503, "The original file is unavailable. Check the originals drive.")
        doc = attach_asset(
            db,
            upload,
            asset,
            client_uuid,
            kind,
            options,
            filename or (file.filename if file else ""),
        )
        db.commit()
        return asset, doc, True
    incoming = settings.assets_dir / ".incoming"
    incoming.mkdir(exist_ok=True, mode=0o750)
    temporary = incoming / str(uuid4())
    checksum, size = hashlib.sha256(), 0
    try:
        with temporary.open("xb") as stream:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > max(settings.image_limit_bytes, settings.pdf_limit_bytes):
                    raise HTTPException(413, "This file is too large.")
                guard.require_ready()
                checksum.update(chunk)
                stream.write(chunk)
        sha = checksum.hexdigest()
        if expected_sha and expected_sha != sha:
            raise HTTPException(422, "The file changed during upload. Please try again.")

        # fsync, PDF parsing and DB writes block; keep them off the event loop.
        def finish() -> tuple[Asset, Document, bool]:
            with temporary.open("rb") as stored:
                os.fsync(stored.fileno())
            details = inspect_file(temporary, settings)
            if db.bind.dialect.name == "postgresql":
                lock_id = int.from_bytes(bytes.fromhex(sha[:16]), signed=True)
                db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
            existing = db.scalar(select(Asset).where(Asset.sha256 == sha))
            if existing:
                asset = existing
                destination = asset_path(settings.assets_dir, asset.storage_path)
                if not destination.is_file():
                    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
                    os.link(temporary, destination)
                    dir_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(dir_fd)
                    finally:
                        os.close(dir_fd)
                asset.purged_at = None
            else:
                asset_id = uuid4()
                relative = f"{str(asset_id)[:2]}/{asset_id}/original.{details.pop('extension')}"
                destination = asset_path(settings.assets_dir, relative)
                guard.require_ready()
                destination.parent.mkdir(parents=True, mode=0o750)
                os.link(temporary, destination)
                dir_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
                asset = Asset(
                    id=asset_id,
                    sha256=sha,
                    storage_path=relative,
                    original_filename=safe_name(file.filename or "Untitled"),
                    bytes=size,
                    **details,
                )
                db.add(asset)
                db.flush()
            doc = attach_asset(
                db,
                upload,
                asset,
                client_uuid,
                kind,
                options,
                filename or (file.filename if file else ""),
            )
            db.commit()
            return asset, doc, existing is not None

        return await run_in_threadpool(finish)
    finally:
        temporary.unlink(missing_ok=True)
        await file.close()
