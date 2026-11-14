"""Seed only the disposable audit database; never run against the owner library."""
import os
if os.environ.get('EXPO_SYNTHETIC_AUDIT') != '1':
    raise SystemExit('Disposable audit container required.')
import hashlib
from uuid import uuid4
from PIL import Image, ImageDraw
from sqlalchemy.orm import Session
from app.core.config import Settings
from app.db.session import build_engine
from app.db.library import Asset, Document, DocumentPage, Expo, UploadSession
from app.db.intelligence import Company, Proposal
from app.domain.fields import proposal

settings = Settings()
with Session(build_engine(settings)) as db:
    for mode in ('desktop', 'phone'):
        name = 'SYNTHETIC Review '+mode+' '+str(uuid4())[:6]
        relative = f'audit/{uuid4()}.png'
        path = settings.assets_dir / relative
        path.parent.mkdir(exist_ok=True)
        image = Image.new('RGB', (640, 360), 'white')
        draw = ImageDraw.Draw(image)
        for i, text in enumerate((name, '+1 202 555 0101', 'kept@example.com', 'new@example.com', 'broken@@example.com', 'Possib1y Misspe1led Road')):
            draw.text((25, 35+i*45), text, fill='black', font_size=22)
        image.save(path)
        asset = Asset(storage_path=relative, sha256=hashlib.sha256(path.read_bytes()).hexdigest(), original_filename=name+'.png', bytes=path.stat().st_size, mime='image/png', page_count=1, width=640, height=360)
        expo = Expo(name=name)
        company = Company(display_name=name, channels=[{'kind':'phone','raw':'+1 202 555 0101'}, {'kind':'email','raw':'kept@example.com'}])
        db.add_all([asset, expo, company]); db.flush()
        batch = UploadSession(expo_id=expo.id); db.add(batch); db.flush()
        doc = Document(expo_id=expo.id, upload_session_id=batch.id, ingest_key='review', company_id=company.id, title=name, type='card', processing_state='ready', review_state='needs_attention', group_state='confirmed', review_reasons=['Synthetic OCR discrepancy; compare printed contact details.'])
        db.add(doc); db.flush()
        page = DocumentPage(document_id=doc.id, asset_id=asset.id, order=0, role='front'); db.add(page); db.flush()
        proposal(db, 'company', company.id, 'channels', [
            {'kind':'phone','raw':'+12025550101'}, company.channels[1],
            {'kind':'email','raw':'broken@@example.com'},
            {'kind':'email','raw':'new@example.com'},
            {'kind':'address','raw':'Possib1y Misspe1led Road'},
        ], reason='Synthetic OCR discrepancy', document_id=doc.id, evidence=[{'page_id':str(page.id),'quote':'new@example.com'}])
        db.add(Proposal(entity_type='company', entity_id=company.id, field='display_name', current_value=name, proposed_value=name, reason='Legacy no-op', document_id=doc.id))
        print(mode, name)
    db.commit()
