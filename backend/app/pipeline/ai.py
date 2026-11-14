import hashlib
import re
from difflib import SequenceMatcher
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.intelligence import (
    Appearance,
    Company,
    Contact,
    ContactChannel,
    DuplicateSuggestion,
    FieldValue,
)
from app.db.library import Document, DocumentPage
from app.db.processing import ExtractionRun, OCRResult, SearchChunk
from app.domain import fields, providers
from app.domain.contact_values import (
    channel_issue,
    channel_key,
    contact_owner_issue,
    normalise_channel,
)
from app.domain.review import for_document, region_hint
from app.providers.base import ProviderFailure
from app.providers.schema import Extraction


def source_pages(db: Session, document: Document) -> dict[str, str]:
    result = {}
    for page in db.scalars(
        select(DocumentPage)
        .where(DocumentPage.document_id == document.id)
        .order_by(DocumentPage.order)
    ):
        ocr = db.scalar(
            select(OCRResult)
            .where(OCRResult.document_page_id == page.id)
            .order_by(OCRResult.revision.desc())
            .limit(1)
        )
        if ocr:
            result[str(page.id)] = ocr.text
    return result


def text_batches(pages: dict[str, str], document_id: UUID, size: int = 12000) -> list[str]:
    batches, buffer = [], ""
    for number, (id, text) in enumerate(pages.items(), 1):
        for start in range(0, max(1, len(text)), size - 500):
            part = f"Document {document_id}\nPage P{number} [{id}]\n<untrusted_document_text>\n{text[start : start + size - 500]}\n</untrusted_document_text>\n"
            if buffer and len(buffer) + len(part) > size:
                batches.append(buffer)
                buffer = ""
            buffer += part
    if buffer:
        batches.append(buffer)
    return batches


def normal(value: str) -> str:
    return " ".join(value.casefold().split())


def verified(value: str, evidence, pages: dict[str, str], *, interleaved=False) -> bool:
    quote = normal(evidence.quote)
    source = normal(pages.get(str(evidence.page_id), ""))
    matches = quote in source
    if interleaved and quote and not matches:
        # Address lines can be separated by another column. Match exact words in order, with bounded gaps.
        words = quote.split()
        pattern = r"\b" + r"(?:\s+\S+){0,12}\s+".join(re.escape(word) for word in words) + r"\b"
        matches = bool(re.search(pattern, source))
    return bool(quote and matches and normal(value) in quote)


def save_channels(
    db: Session,
    owner_type: str,
    owner_id: UUID,
    values,
    pages,
    reasons: list[str],
    *,
    document_id=None,
    run_id=None,
    ambiguous_owner=False,
    person_name="",
    other_names=(),
):
    row = fields.entity(db, owner_type, owner_id)
    combined = list(row.channels)
    region = region_hint(db)
    held = []
    for channel in values:
        if not verified(
            channel.raw, channel.evidence, pages, interleaved=channel.kind == "address"
        ):
            reasons.append(f"{channel.kind}: printed evidence does not match the suggested value.")
            continue
        incoming = channel.model_dump(mode="json")
        if any(
            channel_key(item, region) == channel_key(incoming, region) for item in combined + held
        ):
            continue
        issue = channel_issue(incoming, region) or contact_owner_issue(
            db, owner_type, owner_id, incoming, region
        )
        if ambiguous_owner and channel.kind in ("phone", "email"):
            quote = normal(channel.evidence.quote)
            if (
                not person_name
                or normal(person_name) not in quote
                or any(normal(name) in quote for name in other_names)
            ):
                reasons.append(
                    f"Unassigned {channel.kind}: {channel.raw}. Person-to-contact association is uncertain for {person_name}; check the source before adding it to a person."
                )
                continue
        if issue or channel.kind == "address":
            reasons.append(issue or "Address spelling needs comparison with the source.")
            held.append(incoming)
        else:
            combined.append(incoming)
    if held:
        fields.proposal(
            db,
            owner_type,
            owner_id,
            "channels",
            combined + held,
            reason="Check these contact details against the source before accepting. "
            + " ".join(dict.fromkeys(reasons)),
            document_id=document_id,
            evidence=[item["evidence"] for item in held if item.get("evidence")],
        )
    if combined and not held:
        fields.set_field(
            db,
            owner_type,
            owner_id,
            "channels",
            combined,
            source="extracted",
            actor="ai",
            document_id=document_id,
            run_id=run_id,
            evidence=[item["evidence"] for item in combined if item.get("evidence")],
        )


def appearance(db: Session, company: Company, document: Document, contact: Contact | None = None):
    condition = Appearance.contact_id == contact.id if contact else Appearance.contact_id.is_(None)
    if not db.scalar(
        select(Appearance.id).where(
            Appearance.company_id == company.id, Appearance.document_id == document.id, condition
        )
    ):
        db.add(
            Appearance(
                company_id=company.id,
                contact_id=contact.id if contact else None,
                document_id=document.id,
                expo_id=document.expo_id,
            )
        )


def apply_extraction(
    db: Session, document: Document, value: Extraction, pages: dict[str, str], run: ExtractionRun
):
    company = db.get(Company, document.company_id) if document.company_id else None
    if not company:
        assets = list(
            db.scalars(select(DocumentPage.asset_id).where(DocumentPage.document_id == document.id))
        )
        candidate = db.scalar(
            select(Document.company_id)
            .join(DocumentPage)
            .where(
                DocumentPage.asset_id.in_(assets),
                Document.id != document.id,
                Document.company_id.is_not(None),
                Document.deleted_at.is_(None),
            )
        )
        company = db.get(Company, candidate) if candidate else Company()
        db.add(company)
        db.flush()
        document.company_id = company.id
    reasons = list(document.review_reasons) + value.review_reasons
    if value.website:
        domain = value.website.value.lower().removeprefix("https://").removeprefix("http://")
        domain = domain.removeprefix("www.").split("/")[0]
        channels = list(value.channels) + [
            channel for person in value.people for channel in person.channels
        ]
        for channel in channels:
            email_domain = channel.raw.rpartition("@")[2].lower()
            if (
                channel.kind == "email"
                and email_domain
                and email_domain != domain
                and SequenceMatcher(None, email_domain, domain).ratio() >= 0.8
            ):
                reasons.append(
                    f"Check {channel.raw} against the original: its domain differs slightly "
                    "from the printed website, which may be an OCR error."
                )
    for incoming, field in {
        "company_name": "display_name",
        "website": "website",
        "description": "description",
        "business_role": "business_role",
    }.items():
        item = getattr(value, incoming)
        if not item:
            continue
        evidence = [item.evidence.model_dump(mode="json")]
        if verified(item.value, item.evidence, pages):
            fields.set_field(
                db,
                "company",
                company.id,
                field,
                item.value,
                source="extracted",
                evidence=evidence,
                run_id=run.id,
                document_id=document.id,
                actor="ai",
            )
        else:
            reasons.append(f"{field.replace('_', ' ')} has no matching printed evidence.")
            if field in ("description", "business_role"):
                fields.proposal(
                    db,
                    "company",
                    company.id,
                    field,
                    item.value,
                    reason="AI suggestion needs your check.",
                    evidence=evidence,
                    document_id=document.id,
                )
    for field in ("products", "services", "categories"):
        supported = [
            item for item in getattr(value, field) if verified(item.value, item.evidence, pages)
        ]
        if len(supported) != len(getattr(value, field)):
            reasons.append(f"Some {field} have no matching printed evidence.")
        if supported:
            values = list(
                dict.fromkeys(getattr(company, field) + [item.value for item in supported])
            )
            fields.set_field(
                db,
                "company",
                company.id,
                field,
                values,
                source="extracted",
                evidence=[item.evidence.model_dump(mode="json") for item in supported],
                run_id=run.id,
                document_id=document.id,
                actor="ai",
            )
    save_channels(
        db,
        "company",
        company.id,
        value.channels,
        pages,
        reasons,
        document_id=document.id,
        run_id=run.id,
    )
    appearance(db, company, document)
    for person in value.people:
        if person.full_name and re.fullmatch(
            r"(?i)(sr\.?\s*|senior\s*|jr\.?\s*|junior\s*)?(manager|director|sales|engineer|sales manager|proprietor|owner|ceo|founder)",
            person.full_name.value.strip(),
        ):
            reasons.append("A job title was returned as a person name. Check the printed name.")
            continue
        if not person.full_name or not verified(
            person.full_name.value, person.full_name.evidence, pages
        ):
            reasons.append("A person's name has no matching printed evidence.")
            continue
        identity = (
            normal(person.full_name.value)
            + "|"
            + "|".join(
                sorted(
                    normalise_channel(channel.kind, channel.raw)
                    for channel in person.channels
                    if channel.kind in ("phone", "email")
                )
            )
        )
        if not person.channels:
            identity += str(document.id)
        key = hashlib.sha256(identity.encode()).hexdigest()
        contact = db.scalar(
            select(Contact).where(Contact.company_id == company.id, Contact.source_key == key)
        )
        if not contact:
            anchored = []
            for previous in db.scalars(
                select(Contact).where(
                    Contact.source_document_id == document.id, Contact.deleted_at.is_(None)
                )
            ):
                names = db.scalars(
                    select(FieldValue).where(
                        FieldValue.entity_id == previous.id, FieldValue.field == "full_name"
                    )
                )
                if normal(previous.full_name) == normal(person.full_name.value) or any(
                    normal(str(name.value)) == normal(person.full_name.value)
                    and any(
                        item.get("page_id") == str(person.full_name.evidence.page_id)
                        for item in name.evidence
                    )
                    for name in names
                ):
                    anchored.append(previous)
            if len(anchored) == 1:
                contact = anchored[0]
        if not contact:
            contact = Contact(company_id=company.id, source_document_id=document.id, source_key=key)
            db.add(contact)
            db.flush()
        for field in ("full_name", "designation", "department"):
            item = getattr(person, field)
            if item and verified(item.value, item.evidence, pages):
                fields.set_field(
                    db,
                    "contact",
                    contact.id,
                    field,
                    item.value,
                    source="extracted",
                    evidence=[item.evidence.model_dump(mode="json")],
                    run_id=run.id,
                    document_id=document.id,
                    actor="ai",
                )
            elif item:
                reasons.append(f"{field.replace('_', ' ')} has no matching printed evidence.")
        save_channels(
            db,
            "contact",
            contact.id,
            person.channels,
            pages,
            reasons,
            document_id=document.id,
            run_id=run.id,
            ambiguous_owner=len([entry for entry in value.people if entry.full_name]) > 1
            or db.scalar(
                select(func.count(Contact.id)).where(
                    Contact.source_document_id == document.id, Contact.deleted_at.is_(None)
                )
            )
            > 1,
            person_name=person.full_name.value,
            other_names=[
                entry.full_name.value
                for entry in value.people
                if entry.full_name
                and normal(entry.full_name.value) != normal(person.full_name.value)
            ],
        )
        appearance(db, company, document, contact)
    db.flush()
    protected_title = db.scalar(
        select(FieldValue.id).where(
            FieldValue.entity_type == "document",
            FieldValue.entity_id == document.id,
            FieldValue.field == "title",
            FieldValue.is_current.is_(True),
            FieldValue.source == "user",
        )
    )
    if not protected_title:
        people = list(
            db.scalars(
                select(Contact.full_name)
                .join(Appearance, Appearance.contact_id == Contact.id)
                .where(Appearance.document_id == document.id, Contact.deleted_at.is_(None))
                .order_by(Contact.full_name)
            )
        )
        title_parts = (
            [company.display_name or "Unidentified company"]
            + ([people[0]] if people else [])
            + [{"card": "Visiting Card", "brochure": "Brochure"}.get(document.type, "Document")]
        )
        if company.display_name == "Unidentified company":
            title_parts.append(str(document.id)[:4].upper())
        fields.set_field(
            db,
            "document",
            document.id,
            "title",
            " — ".join(title_parts)[:400],
            source="ai_normalised",
            run_id=run.id,
            document_id=document.id,
            actor="ai",
            generated=True,
        )
    own_channels = list(
        db.scalars(
            select(ContactChannel).where(
                ContactChannel.owner_type == "company", ContactChannel.owner_id == company.id
            )
        )
    )
    for channel in own_channels:
        if channel.kind not in ("email", "phone", "web"):
            continue
        for candidate in db.scalars(
            select(ContactChannel.owner_id).where(
                ContactChannel.owner_type == "company",
                ContactChannel.owner_id != company.id,
                ContactChannel.normalised == channel.normalised,
            )
        ):
            exists = db.scalar(
                select(DuplicateSuggestion.id).where(
                    DuplicateSuggestion.source_id == company.id,
                    DuplicateSuggestion.candidate_id == candidate,
                )
            )
            if not exists:
                db.add(
                    DuplicateSuggestion(
                        entity_type="company",
                        source_id=company.id,
                        candidate_id=candidate,
                        reason=f"Shared {channel.kind}. Please compare the sources.",
                    )
                )
    db.execute(
        update(SearchChunk)
        .where(SearchChunk.document_id == document.id)
        .values(company_id=company.id)
    )
    document.review_reasons = list(dict.fromkeys(reasons))
    pending = for_document(db, document)
    if reasons or pending:
        document.review_state = "needs_attention"


def extract_document(db: Session, document: Document, settings: Settings):
    input_revision = document.revision
    pages = source_pages(db, document)
    if not any(text.strip() for text in pages.values()):
        document.review_state = "needs_attention"
        document.review_reasons = list(
            dict.fromkeys(document.review_reasons + ["No readable text to extract."])
        )
        document.processing_state = "needs_review"
        return
    for number, text in enumerate(text_batches(pages, document.id)):
        completed = [
            run
            for run in db.scalars(
                select(ExtractionRun).where(
                    ExtractionRun.document_id == document.id,
                    ExtractionRun.stage == "ai",
                    ExtractionRun.input_revision == document.revision,
                    ExtractionRun.status == "succeeded",
                )
            )
            if run.output.get("chunk_number") == number
        ]
        if completed:
            continue
        try:
            context = document.processing_options.get("instructions", "")
            if context:
                import json

                text += "\nOwner context (not printed evidence): " + json.dumps(context)
            value, metadata = providers.extract(db, settings, text)
        except (providers.InvalidExtraction, ProviderFailure) as error:
            db.refresh(document)
            if (
                document.revision != input_revision
                or document.deleted_at
                or document.group_state != "confirmed"
            ):
                return
            document.review_state = "needs_attention"
            document.review_reasons = list(dict.fromkeys(document.review_reasons + [str(error)]))
            db.add(
                ExtractionRun(
                    document_id=document.id,
                    stage="ai",
                    provider=getattr(error, "provider", "unavailable"),
                    model=getattr(error, "model", ""),
                    input_revision=document.revision,
                    status="needs_review",
                    error=str(error),
                )
            )
            document.processing_state = "failed"
            db.commit()
            return
        db.refresh(document)
        if (
            document.revision != input_revision
            or document.deleted_at
            or document.group_state != "confirmed"
        ):
            return
        run = ExtractionRun(
            document_id=document.id,
            stage="ai",
            provider=metadata["provider"],
            model=metadata["model"],
            version=metadata["version"],
            input_revision=document.revision,
            status="succeeded",
            output={"chunk_number": number, "data": value.model_dump(mode="json"), **metadata},
        )
        db.add(run)
        db.flush()
        apply_extraction(db, document, value, pages, run)
        db.commit()
    stale = db.scalar(
        select(SearchChunk.id)
        .where(SearchChunk.document_id == document.id, SearchChunk.embedding.is_(None))
        .limit(1)
    )
    document.processing_state = "indexing" if stale else "ready"
