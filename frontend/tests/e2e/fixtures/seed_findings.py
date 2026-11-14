"""Create reproducible audit data only in a disposable stack."""
import os
if os.environ.get('EXPO_SYNTHETIC_AUDIT') != '1':
    raise SystemExit('Disposable audit database required.')
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import Settings
from app.db.session import build_engine
from app.db.library import Expo, Document, DocumentPage
from app.db.intelligence import Company, Contact
from app.domain import fields
from app.pipeline.ai import appearance
with Session(build_engine(Settings())) as db:
    for mode in ('desktop','phone'):
        source=db.scalar(select(Document).join(Expo,Expo.id==Document.expo_id).where(Expo.name.like('SYNTHETIC Review '+mode+' %')).order_by(Expo.created_at.desc()))
        company=db.get(Company,source.company_id)
        page=db.scalar(select(DocumentPage).where(DocumentPage.document_id==source.id))
        source.title='SYNTHETIC findings '+mode+' '+str(uuid4())[:6]
        source.review_state='needs_attention'
        company.channels=[{'kind':'address','label':'Office address','raw':'New Colony\nSoyepur','evidence':{'page_id':str(page.id),'quote':'New Colony\nSoyepur'}}]
        existing=list(db.scalars(select(Contact).where(Contact.company_id==company.id)))
        for i in range(len(existing),7):
            person=Contact(company_id=company.id,source_document_id=source.id,full_name=f'Fictional Audit Person {i}',channels=[])
            db.add(person);db.flush();appearance(db,company,source,person)
        fields.proposal(db,'company',company.id,'description','Synthetic description needs review',reason='Synthetic pending review',document_id=source.id)
        print(mode,source.id,company.id)
    db.commit()
