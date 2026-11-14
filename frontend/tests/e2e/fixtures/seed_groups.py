"""Seed only a disposable audit database; never run against the owner library."""
import os

if os.environ.get("EXPO_SYNTHETIC_AUDIT") != "1":
    raise SystemExit("Set EXPO_SYNTHETIC_AUDIT=1 only in the disposable audit container.")

from sqlalchemy import select
from PIL import Image
from pathlib import Path
from uuid import uuid4
import hashlib
from sqlalchemy.orm import Session
from app.core.config import Settings
from app.db.session import build_engine
from app.db.library import Asset, Document, DocumentPage, Expo, UploadSession
with Session(build_engine(Settings())) as db:

    for mode in ('desktop', 'phone'):
        asset_id = uuid4()
        relative = f"audit/{asset_id}.png"
        path = Settings().assets_dir / relative
        path.parent.mkdir(exist_ok=True)
        Image.new('RGB', (600, 350), 'white' if mode == 'desktop' else 'ivory').save(path)
        asset = Asset(id=asset_id, storage_path=relative, sha256=hashlib.sha256(path.read_bytes()).hexdigest(), original_filename='AUDIT-'+mode+'.png', bytes=path.stat().st_size, mime='image/png', page_count=1, width=600, height=350)
        db.add(asset)
        expo = Expo(name='AUDIT grouping final '+mode)
        db.add(expo)
        db.flush()
        batch = UploadSession(expo_id=expo.id)
        db.add(batch)
        db.flush()
        for name in ('front', 'back'):
            doc = Document(expo_id=expo.id, upload_session_id=batch.id, ingest_key=name, title='AUDIT '+name, type='card', processing_state='waiting_grouping', group_state='suggested')
            db.add(doc)
            db.flush()
            db.add(DocumentPage(document_id=doc.id, asset_id=asset.id, order=0, role=name))
    db.commit()
print('Seeded synthetic grouping batches.')
