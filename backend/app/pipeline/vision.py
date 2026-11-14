"""Explicit local-only image checks create proposals, never verified OCR facts."""

import base64
import io

from PIL import Image
from sqlalchemy import select

from app.db.intelligence import Company, Contact, ProviderSetting
from app.db.library import DocumentPage
from app.db.processing import AssetDerivative, ExtractionRun
from app.domain import fields, providers
from app.providers.base import ProviderFailure


def image_check(db, document, settings, pages):
    revision = document.revision
    previous = db.scalar(
        select(ExtractionRun).where(
            ExtractionRun.document_id == document.id,
            ExtractionRun.stage == "vision",
            ExtractionRun.input_revision == document.revision,
        )
    )
    if previous:
        return
    row = db.scalar(select(ProviderSetting).where(ProviderSetting.provider == "ollama"))
    try:
        if not row or not row.enabled:
            raise ProviderFailure("Enable a local Ollama vision model for the image check.")
        adapter = providers.adapter(row, settings)
        info = adapter.inspect_model()
        if info["remote"]:
            raise ProviderFailure("Image checks require a local Ollama model; no images were sent.")
        if row.config.get("pinned_digest") and row.config["pinned_digest"] != info["model_digest"]:
            raise ProviderFailure(
                "The pinned model changed; review its version before sending images."
            )
        import ipaddress
        import socket
        from urllib.parse import urlsplit

        host = urlsplit(adapter.base_url).hostname
        addresses = socket.getaddrinfo(host, None)
        if not addresses or any(ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ProviderFailure(
                "Image checks require a LAN, loopback or VPN Ollama address; no images were sent."
            )
        response = adapter.client.post(
            adapter.base_url + "/api/show", json={"model": row.model}, timeout=15
        )
        response.raise_for_status()
        if "vision" not in response.json().get("capabilities", []):
            raise ProviderFailure(
                "The selected Ollama model does not report vision support. Choose a vision model in Settings."
            )
        images, attached_pages = [], {}
        for page in db.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_id == document.id)
            .order_by(DocumentPage.order)
        ):
            if len(images) == 4:
                break
            derivative = db.scalar(
                select(AssetDerivative).where(
                    AssetDerivative.document_page_id == page.id,
                    AssetDerivative.kind == "ocr",
                    AssetDerivative.revision == document.revision,
                )
            )
            if derivative:
                with Image.open(settings.previews_dir / derivative.path) as image:
                    image.thumbnail((1400, 1400))
                    stream = io.BytesIO()
                    image.convert("RGB").save(stream, format="JPEG", quality=92)
                    images.append(base64.b64encode(stream.getvalue()).decode())
                    attached_pages[str(page.id)] = pages.get(str(page.id), "")[:1800]
        if not images:
            raise ProviderFailure("No prepared images are available for this check.")
        from app.pipeline.ai import text_batches

        prompt = (
            "\n".join(text_batches(attached_pages, document.id))
            + "\nCompare the attached card photos with OCR. Report uncertain logo/email/number characters. Output remains a suggestion for human review."
        )
        prompt += "\nOwner context (not printed evidence): " + document.processing_options.get(
            "instructions", ""
        )
        reply = adapter.extract(prompt, images=images)
        value = providers.decode_extraction(reply.text, prompt, require_complete=False)

        def check_sources(item):
            if isinstance(item, dict):
                if "page_id" in item and item["page_id"] not in attached_pages:
                    raise ProviderFailure(
                        "The image model returned an unknown source page. Reprocess the image check; no suggestions were saved."
                    )
                for child in item.values():
                    check_sources(child)
            elif isinstance(item, list):
                for child in item:
                    check_sources(child)

        check_sources(value.model_dump(mode="json"))
        db.refresh(document)
        if (
            document.revision != revision
            or document.deleted_at
            or document.group_state != "confirmed"
        ):
            return
        if not document.company_id:
            company = Company()
            db.add(company)
            db.flush()
            document.company_id = company.id
            from app.pipeline.ai import appearance

            appearance(db, company, document)
        reason = "Local image-model suggestion. Compare with the photo before accepting; not OCR-verified."
        for field, item in (("display_name", value.company_name), ("website", value.website)):
            if item:
                fields.proposal(
                    db,
                    "company",
                    document.company_id,
                    field,
                    item.value,
                    reason=reason,
                    evidence=[item.evidence.model_dump(mode="json")],
                    document_id=document.id,
                    actor="image-check",
                )
        people = list(
            db.scalars(
                select(Contact).where(
                    Contact.source_document_id == document.id, Contact.deleted_at.is_(None)
                )
            )
        )
        if len(people) == 1 and len(value.people) == 1:
            for field in ("full_name", "designation", "department"):
                item = getattr(value.people[0], field)
                if item:
                    fields.proposal(
                        db,
                        "contact",
                        people[0].id,
                        field,
                        item.value,
                        reason=reason,
                        evidence=[item.evidence.model_dump(mode="json")],
                        document_id=document.id,
                        actor="image-check",
                    )
        for kind, target, channels in [("company", document.company_id, value.channels)] + (
            [("contact", people[0].id, value.people[0].channels)]
            if len(people) == 1 and len(value.people) == 1
            else []
        ):
            if channels:
                old = fields.entity(db, kind, target).channels
                incoming = [item.model_dump(mode="json") for item in channels]
                keys = {(item["kind"], item.get("label", "")) for item in incoming}
                merged = [
                    item for item in old if (item["kind"], item.get("label", "")) not in keys
                ] + incoming
                fields.proposal(
                    db,
                    kind,
                    target,
                    "channels",
                    merged,
                    reason=reason,
                    document_id=document.id,
                    actor="image-check",
                )
        db.add(
            ExtractionRun(
                document_id=document.id,
                stage="vision",
                provider="ollama",
                model=row.model,
                version=info["model_digest"],
                input_revision=document.revision,
                status="succeeded",
                output={
                    "data": value.model_dump(mode="json"),
                    "cloud": False,
                    "suggestions_only": True,
                },
            )
        )
        document.review_state = "needs_attention"
        document.review_reasons = list(
            dict.fromkeys(
                document.review_reasons
                + [
                    "Image check created suggestions; compare logo, email and number characters with the source."
                ]
            )
        )
    except Exception as error:
        db.refresh(document)
        if (
            document.revision != revision
            or document.deleted_at
            or document.group_state != "confirmed"
        ):
            return
        reason = (
            str(error)
            if isinstance(error, ProviderFailure)
            else "The local image check could not finish. Check vision support and the saved connection."
        )
        db.add(
            ExtractionRun(
                document_id=document.id,
                stage="vision",
                provider="ollama",
                model=row.model if row else "",
                input_revision=document.revision,
                status="needs_review",
                error=reason,
            )
        )
        document.review_reasons = list(dict.fromkeys(document.review_reasons + [reason]))
        document.review_state = "needs_attention"
    db.flush()
