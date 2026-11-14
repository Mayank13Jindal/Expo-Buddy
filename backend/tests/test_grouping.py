from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.library import Document, Expo, UploadSession
from tests.test_library import expo, upload


def test_combine_split_reorder_notes_and_undo(signed_in, engine):
    expo_id = expo(signed_in)
    first_session, first = upload(signed_in, expo_id)
    _, second = upload(signed_in, expo_id)
    ids = [first["document"]["id"], second["document"]["id"]]
    note = signed_in.post(
        "/api/v1/notes", json={"document_id": ids[1], "text": "FAKE booth note"}
    ).json()
    with Session(engine) as db:
        for id in ids:
            db.get(Document, UUID(id)).processing_state = "waiting_grouping"
        db.commit()
    response = signed_in.post("/api/v1/grouping/combine", json={"document_ids": ids})
    assert response.status_code == 200, response.text
    combined = signed_in.get(f"/api/v1/documents/{ids[0]}").json()
    assert len(combined["pages"]) == 2 and combined["notes"][0]["id"] == note["id"]
    page_ids = [page["id"] for page in combined["pages"]]
    ordered = signed_in.post(
        "/api/v1/grouping/reorder",
        json={"document_id": ids[0], "page_ids": list(reversed(page_ids))},
    )
    assert ordered.status_code == 200
    assert signed_in.get(f"/api/v1/documents/{ids[0]}").json()["pages"][0]["id"] == page_ids[1]
    split = signed_in.post(
        "/api/v1/grouping/split", json={"document_id": ids[0], "page_ids": [page_ids[1]]}
    )
    assert split.status_code == 200, split.text
    assert (
        len(signed_in.get(f"/api/v1/documents/{split.json()['document_id']}").json()["pages"]) == 1
    )
    assert (
        signed_in.post(
            "/api/v1/grouping/undo", json={"action_id": split.json()["action_id"]}
        ).status_code
        == 200
    )
    assert len(signed_in.get(f"/api/v1/documents/{ids[0]}").json()["pages"]) == 2
    assert signed_in.get(f"/api/v1/assets/{first['asset']['id']}/original").status_code == 200


def test_accept_500_documents_and_undo_in_one_action(signed_in, engine):
    with Session(engine) as db:
        event = Expo(name="Fictional bulk expo")
        db.add(event)
        db.flush()
        batch = UploadSession(expo_id=event.id)
        db.add(batch)
        db.flush()
        db.add_all(
            [
                Document(
                    expo_id=event.id,
                    upload_session_id=batch.id,
                    title=f"Fake document {index}",
                    processing_state="waiting_grouping",
                )
                for index in range(500)
            ]
        )
        db.commit()
        id = str(batch.id)
    accepted = signed_in.post("/api/v1/grouping/accept-all", json={"upload_session_id": id})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["count"] == 500
    with Session(engine) as db:
        assert all(doc.group_state == "confirmed" for doc in db.scalars(select(Document)))
    restored = signed_in.post(
        "/api/v1/grouping/undo", json={"action_id": accepted.json()["action_id"]}
    )
    assert restored.status_code == 200
    with Session(engine) as db:
        assert all(doc.group_state == "suggested" for doc in db.scalars(select(Document)))
