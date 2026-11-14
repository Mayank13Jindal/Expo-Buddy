from uuid import UUID

from sqlalchemy.orm import Session

from app.db.library import Document
from app.domain.hybrid import rrf
from app.domain.search import keyword_search
from tests.test_library import expo, upload


def test_reciprocal_rank_fusion_deduplicates_each_path():
    a = {"id": "a", "document_id": "a"}
    b = {"id": "b", "document_id": "b"}
    c = {"id": "c", "document_id": "c"}
    assert [row["id"] for row in rrf([a, b], [b, b, c])] == ["b", "a", "c"]


def test_exact_corrected_fields_find_the_source_across_phone_and_web_formats(signed_in, engine):
    from app.domain.hybrid import exact_search

    event = expo(signed_in)
    _, uploaded = upload(signed_in, event)
    document = uploaded["document"]["id"]
    company = signed_in.post(
        "/api/v1/companies",
        json={
            "fields": {
                "display_name": "Fictional Exact Solar",
                "website": "https://www.example.invalid/",
            }
        },
    ).json()["id"]
    assert (
        signed_in.post(
            f"/api/v1/documents/{document}/attach-company", json={"company_id": company}
        ).status_code
        == 200
    )
    assert (
        signed_in.post(
            "/api/v1/contacts",
            json={
                "company_id": company,
                "document_id": document,
                "fields": {
                    "full_name": "Fictional Exact Person",
                    "channels": [
                        {"kind": "phone", "label": "Mobile", "raw": "+1 (202) 555-0123"},
                        {"kind": "email", "label": "Work", "raw": "person@example.invalid"},
                    ],
                },
            },
        ).status_code
        == 201
    )
    with Session(engine) as db:
        for query in (
            "FICTIONAL EXACT SOLAR",
            "fictional exact person",
            "PERSON@EXAMPLE.INVALID",
            "+12025550123",
            "12025550123",
            "example.invalid",
            "https://www.example.invalid/",
        ):
            hits = exact_search(db, query, UUID(event))
            assert len(hits) == 1, query
            assert hits[0]["document_id"] == document and hits[0]["exact_match"], query
            assert exact_search(db, query, UUID(int=0)) == []


def test_note_scope_excludes_note_matches_before_returning_results(signed_in, engine):
    _, doc = upload(signed_in, expo(signed_in))
    signed_in.post(
        "/api/v1/notes",
        json={"document_id": doc["document"]["id"], "text": "FAKE private orchid phrase"},
    )
    with Session(engine) as db:
        assert keyword_search(db, "orchid", include_notes=True)
        assert keyword_search(db, "orchid", include_notes=False) == []


def test_saved_search_and_bulk_move_undo_preserve_original_and_active_expo(signed_in):
    first = expo(signed_in)
    second = expo(signed_in, "Second fictional expo")
    _, saved = upload(signed_in, first)
    id = saved["document"]["id"]
    search = signed_in.post(
        "/api/v1/saved-searches",
        json={"name": "Fake search", "query": "mounting", "filters": {"scope": "all"}},
    )
    assert search.status_code == 201
    assert signed_in.get("/api/v1/saved-searches").json()[0]["query"] == "mounting"
    moved = signed_in.post(
        "/api/v1/bulk", json={"action": "move_expo", "document_ids": [id], "expo_id": second}
    )
    assert moved.status_code == 200, moved.text
    assert signed_in.get(f"/api/v1/documents/{id}").json()["expo_id"] == second
    assert signed_in.get("/api/v1/preferences").json()["active_expo_id"] == first
    assert signed_in.post(f"/api/v1/bulk/{moved.json()['action_id']}/undo").status_code == 200
    assert signed_in.get(f"/api/v1/documents/{id}").json()["expo_id"] == first
    assert signed_in.get(f"/api/v1/assets/{saved['asset']['id']}/original").status_code == 200
    assert signed_in.delete(f"/api/v1/saved-searches/{search.json()['id']}").status_code == 200


def test_crop_and_rotate_only_change_derived_copies(signed_in, engine, settings):
    from app.pipeline.prepare import prepare_document

    _, saved = upload(signed_in, expo(signed_in))
    id, asset = saved["document"]["id"], saved["asset"]["id"]
    doc = signed_in.get(f"/api/v1/documents/{id}").json()
    page_id = doc["pages"][0]["id"]
    original = signed_in.get(f"/api/v1/assets/{asset}/original").content
    assert (
        signed_in.post(
            f"/api/v1/documents/{id}/rotate", json={"page_id": page_id, "degrees": 90}
        ).status_code
        == 200
    )
    assert (
        signed_in.post(
            f"/api/v1/documents/{id}/crop",
            json={"page_id": page_id, "left": 0, "top": 0, "right": 0.5, "bottom": 0.5},
        ).status_code
        == 200
    )
    with Session(engine) as db:
        prepare_document(db, db.get(Document, UUID(id)), settings)
        db.commit()
    assert signed_in.get(f"/api/v1/assets/{asset}/original").content == original
    assert len(signed_in.get(f"/api/v1/documents/{id}/versions").json()) == 2


def test_cached_tokenizer_keeps_short_notes_and_long_tail(tmp_path, monkeypatch):
    from tokenizers import Tokenizer, models, pre_tokenizers

    from app.pipeline.embeddings import MODELS
    from app.pipeline.index import chunks

    tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0, "solar": 1, "tail": 2}, unk_token="[UNK]"))  # noqa: S106
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.enable_padding(length=256)
    tokenizer.enable_truncation(max_length=256)
    folder = tmp_path / "embeddings" / MODELS["minilm"][0]
    folder.mkdir(parents=True)
    tokenizer.save(str(folder / "tokenizer.json"))
    monkeypatch.setenv("MODELS_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "minilm")
    assert chunks("solar tail") == ["solar tail"]
    result = chunks("solar " * 700 + "tail")
    assert len(result) > 3
    assert result[-1].endswith("tail")
    assert all(value.strip() for value in result)
