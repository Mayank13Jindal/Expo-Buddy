import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.storage import StorageGuard, configured_volumes
from app.db.library import Document
from app.db.processing import Job
from app.db.session import build_engine
from app.domain.jobs import WaitForResource, enqueue, fail_or_retry


def execute_job(job_id: UUID, worker_id: str) -> None:
    settings = Settings()
    guard = StorageGuard(configured_volumes(settings))
    engine = build_engine(settings)
    try:
        with Session(engine, expire_on_commit=False) as db:
            job = db.get(Job, job_id)
            if not job or job.state != "running" or job.worker_id != worker_id:
                return
            try:
                guard.require_ready()
                if job.kind == "purge":
                    from app.domain.trash import remove_originals

                    remove_originals(db, job, settings)
                    job.state, job.lease_until, job.error = "succeeded", None, None
                    db.commit()
                    return
                if job.kind == "backup":
                    from app.db.operations import Backup
                    from app.worker.backup import run_backup

                    db.info["backup_metadata"] = True
                    row = db.get(Backup, job.target_id)
                    if row and row.state != "complete":
                        run_backup(db, row, settings)
                    job.state, job.lease_until, job.error = "succeeded", None, None
                    db.commit()
                    return
                from app.core.maintenance import lock_writes

                lock_writes(db)
                if job.kind == "export":
                    from app.db.exports import Export
                    from app.exports.package import build

                    row = db.get(Export, job.target_id)
                    if row and row.state != "ready":
                        try:
                            build(db, row, settings)
                        except Exception as error:
                            db.rollback()
                            import shutil

                            from app.domain.uploads import asset_path

                            shutil.rmtree(
                                asset_path(settings.exports_dir, str(job.target_id)),
                                ignore_errors=True,
                            )
                            row = db.get(Export, job.target_id)
                            row.state, row.error = (
                                "failed",
                                "The export could not finish. Check free space and original files, then generate a fresh export.",
                            )
                            db.commit()
                            raise error
                    job.state, job.lease_until, job.error = "succeeded", None, None
                    db.commit()
                    return
                if job.kind in ("embed", "reindex"):
                    if job.kind == "embed":
                        from app.pipeline.embeddings import embed_batch

                        embed_batch(db, job.target_id, settings)
                    else:
                        from app.pipeline.index import rebuild_index

                        rebuild_index(db)
                    guard.require_ready()
                    job.state = "succeeded"
                    job.lease_until = None
                    job.error = None
                    db.commit()
                    return
                doc = db.get(Document, job.target_id)
                if not doc or doc.deleted_at or doc.revision != job.input_revision:
                    job.state = "cancelled"
                    db.commit()
                    return
                if job.kind in ("prepare", "rebuild_previews"):
                    from app.pipeline.prepare import prepare_document

                    prepare_document(db, doc, settings)
                    if job.kind == "prepare":
                        doc.processing_state = "reading"
                        enqueue(db, "read", doc.id, doc.revision)
                elif job.kind == "read":
                    from app.pipeline.ocr import read_document

                    read_document(db, doc, settings)
                elif job.kind == "ai":
                    from app.pipeline.ai import extract_document

                    extract_document(db, doc, settings)
                elif job.kind == "vision":
                    from app.pipeline.ai import source_pages
                    from app.pipeline.vision import image_check

                    if doc.group_state == "confirmed":
                        image_check(db, doc, settings, source_pages(db, doc))
                else:
                    raise WaitForResource("This processing step is not available yet.")
                current_revision = db.scalar(select(Document.revision).where(Document.id == doc.id))
                if current_revision != job.input_revision:
                    db.rollback()
                    job = db.get(Job, job_id)
                    job.state, job.lease_until = "cancelled", None
                    db.commit()
                    return
                guard.require_ready()
                current_owner = db.scalar(
                    select(Job.worker_id).where(Job.id == job_id).with_for_update()
                )
                if current_owner != worker_id:
                    db.rollback()
                    return
                job.state = "succeeded"
                job.lease_until = None
                job.error = None
                db.commit()
            except WaitForResource as error:
                db.rollback()
                job = db.get(Job, job_id)
                fail_or_retry(db, job, str(error), waiting=True)
            except Exception:
                db.rollback()
                job = db.get(Job, job_id)
                fail_or_retry(db, job, "Processing could not finish. Retry or check system health.")
                if job.state == "failed":
                    doc = db.get(Document, job.target_id)
                    if doc:
                        doc.processing_state = "failed"
                        db.commit()
                logging.getLogger("worker").warning("job_failed", extra={"event": "job_failed"})
    finally:
        engine.dispose()
