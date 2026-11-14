from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.intelligence import Company, Contact, FieldValue, Proposal, ProviderSetting
from app.db.library import Document, DocumentPage, Note, Owner
from app.db.processing import ExtractionRun
from app.domain import fields, providers
from app.domain.jobs import WaitForResource
from app.pipeline.ai import apply_extraction, normalise_channel, text_batches
from app.providers.base import ProviderFailure, ProviderReply
from app.providers.ollama import Ollama
from app.providers.schema import Extraction
from tests.test_library import expo, upload


def sample(page_id):
    def value(text):
        return {"value": text, "evidence": {"page_id": str(page_id), "quote": text}}

    def channel(kind, raw):
        return {
            "kind": kind,
            "raw": raw,
            "label": "Work",
            "evidence": {"page_id": str(page_id), "quote": raw},
        }

    text = "FICTIONAL SOLAR COMPANY\nFAKE PERSON\nSales Manager\n+12025550101\nexample@example.com\nMounting structures"
    data = {
        "company_name": value("FICTIONAL SOLAR COMPANY"),
        "products": [value("Mounting structures")],
        "people": [
            {
                "full_name": value("FAKE PERSON"),
                "designation": value("Sales Manager"),
                "channels": [
                    channel("phone", "+12025550101"),
                    channel("email", "example@example.com"),
                ],
            }
        ],
    }
    return Extraction.model_validate(data), {str(page_id): text}


def test_user_corrections_notes_proposals_and_idempotent_reprocessing(signed_in, engine):
    _, saved = upload(signed_in, expo(signed_in))
    id = UUID(saved["document"]["id"])
    with Session(engine) as db:
        doc = db.get(Document, id)
        page = db.scalar(select(DocumentPage).where(DocumentPage.document_id == id))
        value, text = sample(page.id)
        run = ExtractionRun(
            document_id=id, stage="ai", provider="fake-local", input_revision=1, status="succeeded"
        )
        db.add(run)
        db.flush()
        apply_extraction(db, doc, value, text, run)
        db.commit()
        company_id = doc.company_id
        contact = db.scalar(select(Contact))
        fields.set_field(
            db, "company", company_id, "display_name", "OWNER CORRECTED FICTIONAL COMPANY"
        )
        fields.set_field(
            db,
            "contact",
            contact.id,
            "channels",
            [{"kind": "phone", "label": "Corrected", "raw": "00098765432"}],
        )
        db.add(Note(document_id=id, text="FAKE private note never sent to AI"))
        db.commit()
        apply_extraction(db, doc, value, text, run)
        db.commit()
        assert db.get(Company, company_id).display_name == "OWNER CORRECTED FICTIONAL COMPANY"
        assert contact.channels[0]["raw"] == "00098765432"
        assert db.scalar(select(func.count(Contact.id))) == 1
        assert db.scalar(select(func.count(Company.id))) == 1
        assert len(list(db.scalars(select(Proposal)))) == 2
        assert "private note" in db.scalar(select(Note)).text
        assert (
            db.scalar(
                select(FieldValue).where(
                    FieldValue.entity_type == "company",
                    FieldValue.field == "display_name",
                    FieldValue.is_current.is_(True),
                )
            ).source
            == "user"
        )


def test_unsupported_digit_and_role_are_not_saved(signed_in, engine):
    _, saved = upload(signed_in, expo(signed_in))
    with Session(engine) as db:
        doc = db.get(Document, UUID(saved["document"]["id"]))
        page = db.scalar(select(DocumentPage).where(DocumentPage.document_id == doc.id))
        data = {
            "company_name": {
                "value": "FICTIONAL",
                "evidence": {"page_id": str(page.id), "quote": "FICTIONAL"},
            },
            "business_role": {
                "value": "Manufacturer",
                "evidence": {"page_id": str(page.id), "quote": "We install panels"},
            },
            "channels": [
                {
                    "kind": "phone",
                    "raw": "9999999999",
                    "evidence": {"page_id": str(page.id), "quote": "9999?99999"},
                }
            ],
        }
        run = ExtractionRun(
            document_id=doc.id, stage="ai", provider="fake", input_revision=1, status="succeeded"
        )
        db.add(run)
        db.flush()
        apply_extraction(
            db,
            doc,
            Extraction.model_validate(data),
            {str(page.id): "FICTIONAL\nWe install panels\n9999?99999"},
            run,
        )
        db.commit()
        company = db.get(Company, doc.company_id)
        assert not company.business_role and not company.channels
        assert doc.review_state == "needs_attention"
        assert any("printed evidence" in reason for reason in doc.review_reasons)


class FakeProvider:
    def __init__(self, output="{}", failure=None):
        self.output, self.failure, self.calls = output, failure, 0

    def maximum_cost(self, text, repair=None):
        return Decimal("0.01")

    def extract(self, text, repair=None):
        self.calls += 1
        if self.failure:
            raise self.failure
        return ProviderReply(self.output, model="fake-pinned-model")


def configure(db):
    owner = db.scalar(select(Owner))
    owner.settings = {"cloud_fallback": True}
    rows = providers.ensure_providers(db)
    for row in rows:
        row.enabled = True
        row.spending_cap = Decimal(10)
    db.commit()


def test_fallback_cooldown_and_truthful_provider(signed_in, engine, settings):
    adapters = {
        "ollama": FakeProvider(failure=ProviderFailure("unreachable", fallback=True)),
        "chatgpt": FakeProvider(failure=ProviderFailure("plan_limit", fallback=True)),
        "openrouter": FakeProvider(),
    }
    with Session(engine, expire_on_commit=False) as db:
        configure(db)
        value, metadata = providers.extract(
            db, settings, "FAKE PRINTED SOURCE", factory=lambda row, config: adapters[row.provider]
        )
        assert metadata["provider"] == "openrouter" and metadata["cloud"]
        assert [item["reason"] for item in metadata["fallback_reasons"]] == [
            "unreachable",
            "plan_limit",
        ]
        providers.extract(
            db, settings, "FAKE SOURCE", factory=lambda row, config: adapters[row.provider]
        )
        assert adapters["ollama"].calls == 1
        assert db.scalar(
            select(ProviderSetting).where(ProviderSetting.provider == "ollama")
        ).cooldown_until


def test_bad_json_repaired_once_and_permission_errors_never_fall_back(signed_in, engine, settings):
    adapters = {name: FakeProvider() for name in providers.ORDER}
    adapters["ollama"] = FakeProvider("not valid json")
    with Session(engine, expire_on_commit=False) as db:
        configure(db)
        with pytest.raises(providers.InvalidExtraction):
            providers.extract(
                db, settings, "FAKE", factory=lambda row, config: adapters[row.provider]
            )
        assert adapters["ollama"].calls == 2 and adapters["openrouter"].calls == 0
        adapters["ollama"] = FakeProvider(failure=ProviderFailure("Permission denied"))
        with pytest.raises(ProviderFailure, match="Permission"):
            providers.extract(
                db, settings, "FAKE", factory=lambda row, config: adapters[row.provider]
            )
        assert adapters["openrouter"].calls == 0


def test_all_providers_off_waits_and_long_brochure_keeps_last_page(signed_in, engine, settings):
    with Session(engine) as db:
        with pytest.raises(WaitForResource):
            providers.extract(db, settings, "FAKE")
    pages = {str(uuid4()): "FIRST " * 8000, str(uuid4()): "LAST PAGE UNIQUE FAKE CONTENT"}
    batches = text_batches(pages, uuid4())
    assert len(batches) > 3 and "LAST PAGE UNIQUE FAKE CONTENT" in batches[-1]
    assert normalise_channel("phone", "00123 45678") == "0012345678"


def test_ollama_payload_is_text_only_and_has_no_tools():
    captured = []

    def handler(request):
        captured.append(request.read().decode())
        return httpx.Response(200, json={"message": {"content": "{}"}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    Ollama("http://fake-ollama.invalid", "fake-model:1", client).extract("FAKE DOCUMENT TEXT")
    assert "FAKE DOCUMENT TEXT" in captured[0] and '"tools"' not in captured[0]
    import json

    payload = json.loads(captured[0])
    assert payload["think"] is False
    assert payload["format"]["type"] == "object"


def test_ollama_adapter_allows_slow_local_inference(settings):
    from types import SimpleNamespace

    settings.ollama_timeout_seconds = 480
    row = SimpleNamespace(
        provider="ollama", model="fake-model", config={"base_url": "http://fake.invalid"}
    )
    provider = providers.adapter(row, settings)
    try:
        assert provider.client.timeout.read == 480
    finally:
        provider.client.close()


def test_merge_and_undo_keep_contacts(signed_in):
    first = signed_in.post("/api/v1/companies", json={"fields": {"display_name": "FAKE A"}}).json()
    second = signed_in.post("/api/v1/companies", json={"fields": {"display_name": "FAKE B"}}).json()
    for company in (first, second):
        assert (
            signed_in.post(
                "/api/v1/contacts",
                json={
                    "company_id": company["id"],
                    "fields": {"full_name": "FAKE Person " + company["display_name"]},
                },
            ).status_code
            == 201
        )
    merged = signed_in.post(
        "/api/v1/merge",
        json={
            "entity_type": "company",
            "source_id": first["id"],
            "target_id": second["id"],
            "values": {"display_name": "FAKE chosen name"},
        },
    )
    assert merged.status_code == 200, merged.text
    assert len(signed_in.get(f"/api/v1/companies/{second['id']}").json()["contacts"]) == 2
    assert signed_in.post(f"/api/v1/history/{merged.json()['history_id']}/undo").status_code == 200
    assert len(signed_in.get(f"/api/v1/companies/{first['id']}").json()["contacts"]) == 1


def test_provider_secrets_are_encrypted_and_not_returned(signed_in, engine):
    secret = "FAKE-" + str(uuid4())
    response = signed_in.put(
        "/api/v1/settings/providers",
        json={
            "cloud_fallback": True,
            "providers": [
                {
                    "provider": "openrouter",
                    "enabled": False,
                    "model": "fake/model-1",
                    "secret": secret,
                    "spending_cap": 5,
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert secret not in signed_in.get("/api/v1/settings/providers").text
    with Session(engine) as db:
        encrypted = db.scalar(
            select(ProviderSetting).where(ProviderSetting.provider == "openrouter")
        ).encrypted_secret
        assert encrypted and secret not in encrypted


def test_ollama_remote_model_is_detected_before_document_text_leaves(signed_in, engine, settings):
    import httpx
    import pytest

    from app.domain import providers
    from app.domain.jobs import WaitForResource
    from app.providers.ollama import Ollama

    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": "fake-model",
                        "remote_host": "https://cloud.example.invalid",
                        "digest": "fake-digest",
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handle))
    with Session(engine) as db:
        row = providers.ensure_providers(db)[0]
        row.enabled, row.model = True, "fake-model"
        db.commit()
        with pytest.raises(WaitForResource):
            providers.extract(
                db,
                settings,
                "FICTIONAL private source text",
                factory=lambda row, settings: Ollama(
                    "http://fake-ollama.invalid", "fake-model", client
                ),
            )
        assert row.config["remote"] is True
    assert len(requests) == 1 and requests[0].url.path == "/api/tags"
    assert b"private source" not in requests[0].content


def test_ollama_short_page_labels_restore_exact_evidence_ids():
    import json

    page_id = str(uuid4())

    def handle(request):
        payload = json.loads(request.content)
        assert f"Page {page_id}" not in payload["messages"][1]["content"]
        assert f"Page P1 [{page_id}]\n" in payload["messages"][1]["content"]
        assert payload["format"]["$defs"]["Evidence"]["properties"]["page_id"]["enum"] == ["P1"]
        assert set(payload["format"]["required"]) == set(payload["format"]["properties"])
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": json.dumps(
                        {
                            "company_name": {
                                "value": "P1 FICTIONAL SERVICES",
                                "evidence": {
                                    "page_id": "P1",
                                    "quote": "P1 FICTIONAL SERVICES",
                                },
                            },
                        }
                    )
                }
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handle))
    source = (
        f"Document {uuid4()}\nPage P1 [{page_id}]\n<untrusted_document_text>\n"
        "P1 FICTIONAL SERVICES\n</untrusted_document_text>\n"
    )
    reply = Ollama("http://fake.invalid", "fake-model", client).extract(source)
    value = providers.decode_extraction(reply.text, source)
    assert str(value.company_name.evidence.page_id) == page_id
    assert value.company_name.value == "P1 FICTIONAL SERVICES"


def test_valid_json_with_missing_printed_company_is_repaired(signed_in, engine, settings):
    import json

    page_id = str(uuid4())
    text = "FICTIONAL POWER PRIVATE LIMITED\nwww.example.invalid\nFAKE PERSON\nSales Manager"

    def sourced(value):
        return {"value": value, "evidence": {"page_id": page_id, "quote": value}}

    complete = {
        "company_name": sourced("FICTIONAL POWER PRIVATE LIMITED"),
        "website": sourced("www.example.invalid"),
        "people": [{"full_name": sourced("FAKE PERSON"), "designation": sourced("Sales Manager")}],
    }

    class RepairProvider(FakeProvider):
        def extract(self, text, repair=None):
            self.calls += 1
            return ProviderReply(json.dumps(complete) if repair else "{}")

    provider = RepairProvider()
    with Session(engine) as db:
        configure(db)
        value, _ = providers.extract(db, settings, text, factory=lambda *_: provider)
        assert provider.calls == 2
        assert value.company_name.value == "FICTIONAL POWER PRIVATE LIMITED"
        assert value.people[0].designation.value == "Sales Manager"


def test_repeatedly_omitted_company_is_not_reported_as_success(signed_in, engine, settings):
    provider = FakeProvider("{}")
    with Session(engine) as db:
        configure(db)
        with pytest.raises(providers.InvalidExtraction):
            providers.extract(
                db, settings, "FICTIONAL POWER PRIVATE LIMITED", factory=lambda *_: provider
            )
        assert provider.calls == 2
        assert providers.ensure_providers(db)[0].last_status == "output_needs_review"


def test_multiline_evidence_allows_interleaved_columns_but_not_changed_digits():
    from app.pipeline.ai import verified
    from app.providers.schema import Evidence

    page_id = uuid4()
    pages = {str(page_id): "Suite 10\n+91 0000000000\nSample Road\nMetro 123456"}
    evidence = Evidence(page_id=page_id, quote="Suite 10\nSample Road\nMetro 123456")
    assert verified("Suite 10 Sample Road Metro 123456", evidence, pages, interleaved=True)
    assert not verified("Suite 10 Sample Road Metro 123457", evidence, pages)
    assert not verified(
        "Suite 10 Sample Road Metro 123456", Evidence(page_id=uuid4(), quote=evidence.quote), pages
    )


def test_similar_email_domain_is_flagged_without_guessing_a_correction(signed_in, engine):
    _, saved = upload(signed_in, expo(signed_in))
    with Session(engine) as db:
        doc = db.get(Document, UUID(saved["document"]["id"]))
        page = db.scalar(select(DocumentPage).where(DocumentPage.document_id == doc.id))
        website, email = "www.example.com", "info@examp1e.com"
        value = Extraction.model_validate(
            {
                "website": {
                    "value": website,
                    "evidence": {"page_id": str(page.id), "quote": website},
                },
                "channels": [
                    {
                        "kind": "email",
                        "raw": email,
                        "evidence": {"page_id": str(page.id), "quote": email},
                    }
                ],
            }
        )
        run = ExtractionRun(
            document_id=doc.id, stage="ai", provider="fake", input_revision=1, status="succeeded"
        )
        db.add(run)
        db.flush()
        apply_extraction(db, doc, value, {str(page.id): website + "\n" + email}, run)
        assert db.get(Company, doc.company_id).channels[0]["raw"] == email
        assert any("domain differs" in reason for reason in doc.review_reasons)
