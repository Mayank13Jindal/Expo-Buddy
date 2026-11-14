from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.capture import CaptureGroup, CaptureItem
from app.db.library import Expo, Note
from app.domain.search import keyword_search
from tests.test_library import expo, upload


def test_offline_retry_latest_note_and_fixed_expo(signed_in, engine):
    client_id = str(uuid4())
    body = {"name": "Fictional offline expo", "client_uuid": client_id}
    first = signed_in.post("/api/v1/sync/expos", json=body).json()
    assert signed_in.post("/api/v1/sync/expos", json=body).json()["id"] == first["id"]
    group = {
        "client_uuid": str(uuid4()),
        "expo_id": first["id"],
        "label": "Fake booth",
        "captured_at": datetime.now(UTC).isoformat(),
    }
    booth = signed_in.post("/api/v1/sync/groups", json=group).json()
    assert signed_in.post("/api/v1/sync/groups", json=group).json()["id"] == booth["id"]
    batch, saved = upload(signed_in, first["id"])
    file = {
        "client_uuid": str(uuid4()),
        "expo_id": first["id"],
        "capture_group_id": booth["id"],
        "document_id": saved["document"]["id"],
        "asset_id": saved["asset"]["id"],
        "sha256": saved["asset"]["sha256"],
    }
    receipt = signed_in.post("/api/v1/sync/files", json=file).json()
    assert signed_in.post("/api/v1/sync/files", json=file).json() == receipt
    other = expo(signed_in, "Another fictional expo")
    assert signed_in.post("/api/v1/sync/files", json={**file, "expo_id": other}).status_code == 409
    note = {
        "client_uuid": str(uuid4()),
        "target_kind": "file",
        "target_id": receipt["id"],
        "text_value": "Fake old phrase",
        "revision": 1,
    }
    assert signed_in.post("/api/v1/sync/notes", json=note).status_code == 200
    assert (
        signed_in.post(
            "/api/v1/sync/notes",
            json={**note, "text_value": "Fictional private orchid", "revision": 2},
        ).status_code
        == 200
    )
    signed_in.post("/api/v1/sync/notes", json=note)  # late retry must not revert an edit
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(CaptureGroup)) == 1
        assert db.scalar(select(func.count()).select_from(CaptureItem)) == 1
        assert db.scalar(select(func.count()).select_from(Note)) == 1
        assert db.scalar(select(func.count()).select_from(Expo)) == 2
        assert keyword_search(db, "orchid", include_notes=True)
        assert not keyword_search(db, "orchid", include_notes=False)
    detail = signed_in.get(f"/api/v1/documents/{saved['document']['id']}").json()
    assert detail["notes"][0]["text"] == "Fictional private orchid"
    assert detail["expo_id"] == first["id"]
    signed_in.post("/api/v1/sync/notes", json={**note, "revision": 3, "deleted": True})
    assert signed_in.get(f"/api/v1/documents/{saved['document']['id']}").json()["notes"] == []


def test_booth_notes_follow_grouping_and_dashboard_counts(signed_in, engine):
    id = expo(signed_in)
    batch, saved = upload(signed_in, id)
    group = signed_in.post(
        "/api/v1/sync/groups",
        json={
            "client_uuid": str(uuid4()),
            "expo_id": id,
            "label": "Example booth",
            "captured_at": datetime.now(UTC).isoformat(),
        },
    ).json()
    signed_in.post(
        "/api/v1/sync/files",
        json={
            "client_uuid": str(uuid4()),
            "expo_id": id,
            "capture_group_id": group["id"],
            "document_id": saved["document"]["id"],
            "asset_id": saved["asset"]["id"],
            "sha256": saved["asset"]["sha256"],
        },
    )
    note = {
        "client_uuid": str(uuid4()),
        "target_kind": "group",
        "target_id": group["id"],
        "text_value": "Fictional booth note",
        "revision": 1,
    }
    assert signed_in.post("/api/v1/sync/notes", json=note).status_code == 200
    assert (
        signed_in.get(f"/api/v1/documents/{saved['document']['id']}").json()["notes"][0]["text"]
        == note["text_value"]
    )
    assert signed_in.get("/api/v1/dashboard", params={"expo_id": id}).json()["notes"] == 1
