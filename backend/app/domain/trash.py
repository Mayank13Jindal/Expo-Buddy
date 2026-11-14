from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, select

from app.db.library import Asset, Document, DocumentPage, now
from app.db.processing import AssetDerivative
from app.domain.jobs import enqueue


def assets_for_document(db, id):
    ids = set(db.scalars(select(DocumentPage.asset_id).where(DocumentPage.document_id == id)))
    ids.update(
        db.scalars(
            select(AssetDerivative.asset_id)
            .join(DocumentPage)
            .where(DocumentPage.document_id == id)
        )
    )
    return list(db.scalars(select(Asset).where(Asset.id.in_(ids), Asset.purged_at.is_(None))))


def blocked_assets(db, assets, document_id):
    blocked = []
    for asset in assets:
        direct = select(DocumentPage.document_id).where(DocumentPage.asset_id == asset.id)
        versions = (
            select(DocumentPage.document_id)
            .join(AssetDerivative)
            .where(AssetDerivative.asset_id == asset.id)
        )
        if db.scalar(
            select(Document.id)
            .where(
                Document.id != document_id,
                Document.deleted_at.is_(None),
                or_(Document.id.in_(direct), Document.id.in_(versions)),
            )
            .limit(1)
        ):
            blocked.append(asset.id)
    return blocked


def preview(db, doc):
    if not doc.deleted_at:
        raise HTTPException(409, "Move the document to Trash first.")
    assets = assets_for_document(db, doc.id)
    blocked = blocked_assets(db, assets, doc.id)
    return {
        "document_id": doc.id,
        "files": len(assets),
        "bytes": sum(asset.bytes for asset in assets),
        "blocked_file_ids": blocked,
        "can_remove": bool(assets) and not blocked,
    }


def queue_removal(db, doc, confirmation):
    info = preview(db, doc)
    if confirmation != "DELETE":
        raise HTTPException(422, "Type DELETE to confirm removal of these original files.")
    if info["blocked_file_ids"]:
        raise HTTPException(
            409, "These originals are used by another active record and cannot be removed."
        )
    if not info["files"]:
        raise HTTPException(410, "These original files have already been removed.")
    job = enqueue(
        db,
        "purge",
        doc.id,
        doc.revision,
        params={"asset_ids": [str(asset.id) for asset in assets_for_document(db, doc.id)]},
    )
    doc.processing_state = "removing"
    return job


def remove_originals(db, job, settings, *, pause=None):
    import shutil

    from app.domain.uploads import asset_path
    from app.worker.backup import write_pause

    db.info["backup_metadata"] = True
    with (pause or write_pause)(settings):
        doc = db.get(Document, job.target_id)
        if not doc or not doc.deleted_at:
            raise HTTPException(409, "The document was restored. No originals were removed.")
        assets = [db.get(Asset, UUID(id)) for id in job.input["asset_ids"]]
        if blocked_assets(db, assets, doc.id):
            raise HTTPException(409, "An active record uses these originals. Removal stopped.")
        for asset in assets:
            asset.purged_at = now()
        doc.processing_state = "removed"
        # A durable tombstone precedes deletion. A leased retry can finish an interrupted removal.
        db.commit()
        for asset in assets:
            asset_path(settings.assets_dir, asset.storage_path).unlink(missing_ok=True)
            cache = settings.previews_dir / str(asset.id)
            if cache.is_dir():
                shutil.rmtree(cache)
