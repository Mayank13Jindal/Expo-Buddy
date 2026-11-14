import hashlib
from datetime import UTC, datetime, timedelta
from io import BytesIO

from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import aware
from app.db.library import Asset, Document, Owner


def fake_image() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (600, 350), "white").save(stream, format="JPEG")
    return stream.getvalue()


def expo(client, name="Fictional Solar Expo"):
    response = client.post("/api/v1/expos", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload(client, expo_id, content=None):
    session = client.post("/api/v1/upload-sessions", json={"expo_id": expo_id}).json()
    content = content or fake_image()
    result = client.post(
        f"/api/v1/upload-sessions/{session['id']}/files",
        files={"file": ("FAKE-CARD.jpg", content, "image/jpeg")},
        data={"sha256": hashlib.sha256(content).hexdigest()},
    )
    assert result.status_code == 201, result.text
    return session, result.json()


def test_auth_setup_csrf_lockout_and_reset(client, engine):
    assert client.get("/api/v1/expos").status_code == 401
    assert (
        client.post(
            "/api/v1/auth/setup",
            json={"password": "test-setup-password"},
            headers={"origin": "https://wrong.example"},
        ).status_code
        == 403
    )
    response = client.post("/api/v1/auth/setup", json={"password": "test-setup-password"})
    assert response.status_code == 201
    assert "HttpOnly" in response.headers.get_list("set-cookie")[0]
    assert "Secure" in response.headers.get_list("set-cookie")[0]
    assert client.post("/api/v1/expos", json={"name": "Fake"}).status_code == 403
    for _ in range(10):
        assert (
            client.post(
                "/api/v1/auth/login", json={"password": "incorrect-test-password"}
            ).status_code
            == 401
        )
    assert (
        client.post("/api/v1/auth/login", json={"password": "test-setup-password"}).status_code
        == 429
    )
    with Session(engine) as db:
        owner = db.scalar(select(Owner))
        owner.locked_until = None
        db.commit()
    for _ in range(10):
        client.post("/api/v1/auth/login", json={"password": "incorrect-test-password"})
    with Session(engine) as db:
        owner = db.scalar(select(Owner))
        # The second lockout lasts longer than the first.
        assert aware(owner.locked_until) > datetime.now(UTC) + timedelta(seconds=90)
        owner.locked_until = None
        db.commit()
    assert (
        client.post("/api/v1/auth/login", json={"password": "test-setup-password"}).status_code
        == 200
    )
    with Session(engine) as db:
        assert db.scalar(select(Owner)).failed_logins == 0


def test_preference_persists_and_stale_change_is_rejected(signed_in):
    first = expo(signed_in)
    preferences = signed_in.get("/api/v1/preferences").json()
    assert preferences["active_expo_id"] == first
    second = expo(signed_in, "Another Fictional Expo")
    assert (
        signed_in.patch(
            "/api/v1/preferences",
            json={"active_expo_id": second, "expected_revision": preferences["revision"]},
        ).status_code
        == 200
    )
    assert (
        signed_in.patch(
            "/api/v1/preferences",
            json={"active_expo_id": first, "expected_revision": preferences["revision"]},
        ).status_code
        == 409
    )
    assert signed_in.get("/api/v1/preferences").json()["active_expo_id"] == second


def test_upload_context_dedupe_and_note_survive_new_client(signed_in, engine, settings):
    first = expo(signed_in)
    second = expo(signed_in, "Second Fake Expo")
    session, result = upload(signed_in, first)
    sha = result["asset"]["sha256"]
    asset_id = result["asset"]["id"]
    doc_id = result["document"]["id"]
    assert (
        signed_in.patch("/api/v1/preferences", json={"active_expo_id": second}).status_code == 200
    )
    again = signed_in.post(f"/api/v1/upload-sessions/{session['id']}/files", data={"sha256": sha})
    assert again.status_code == 201
    assert again.json()["document"]["id"] == doc_id
    assert again.json()["document"]["expo_id"] == first
    note = signed_in.post(
        "/api/v1/notes", json={"document_id": doc_id, "text": "FAKE personal capture note"}
    )
    assert note.status_code == 201
    _, other = upload(signed_in, second)
    assert other["asset"]["id"] == asset_id
    assert other["document"]["id"] != doc_id
    assert signed_in.get(f"/api/v1/assets/{asset_id}/original").content == fake_image()
    with Session(engine) as db:
        assert db.scalar(select(func.count(Asset.id))) == 1
        assert db.scalar(select(func.count(Document.id))) == 2
    assert (
        signed_in.get(f"/api/v1/documents/{doc_id}").json()["notes"][0]["text"]
        == "FAKE personal capture note"
    )


def test_bad_type_bad_hash_and_missing_drive_cannot_save(signed_in, settings):
    session = signed_in.post("/api/v1/upload-sessions", json={"expo_id": expo(signed_in)}).json()
    endpoint = f"/api/v1/upload-sessions/{session['id']}/files"
    assert (
        signed_in.post(
            endpoint, files={"file": ("bad.jpg", b"<script>bad</script>", "image/jpeg")}
        ).status_code
        == 422
    )
    assert (
        signed_in.post(
            endpoint,
            files={"file": ("fake.jpg", fake_image(), "image/jpeg")},
            data={"sha256": "0" * 64},
        ).status_code
        == 422
    )
    (settings.assets_dir / ".expo-buddy-volume").unlink()
    assert (
        signed_in.post(
            endpoint, files={"file": ("fake.jpg", fake_image(), "image/jpeg")}
        ).status_code
        == 503
    )
    assert not list(settings.assets_dir.glob("**/original.*"))


def test_trash_restore_never_changes_originals(signed_in):
    _, result = upload(signed_in, expo(signed_in))
    id = result["document"]["id"]
    asset_id = result["asset"]["id"]
    assert signed_in.delete(f"/api/v1/documents/{id}").status_code == 200
    assert signed_in.get("/api/v1/documents").json() == []
    assert signed_in.get(f"/api/v1/assets/{asset_id}/original").content == fake_image()
    assert signed_in.post(f"/api/v1/documents/{id}/restore").status_code == 200
    assert len(signed_in.get("/api/v1/documents").json()) == 1


def test_deduplicated_upload_keeps_each_document_filename(signed_in):
    first_expo = expo(signed_in)
    _, first = upload(signed_in, first_expo)
    second_expo = expo(signed_in, "Second expo")
    session = signed_in.post("/api/v1/upload-sessions", json={"expo_id": second_expo}).json()
    response = signed_in.post(f"/api/v1/upload-sessions/{session['id']}/files", data={
        "sha256": first["asset"]["sha256"], "filename": "../SECOND-CARD.jpg"
    })
    assert response.status_code == 201, response.text
    assert response.json()["asset"]["id"] == first["asset"]["id"]
    assert response.json()["document"]["title"] == "SECOND-CARD.jpg"
    assert signed_in.get(f"/api/v1/documents/{first['document']['id']}").json()["title"] == "FAKE-CARD.jpg"
