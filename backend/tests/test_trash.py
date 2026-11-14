from contextlib import nullcontext
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.processing import Job
from app.domain.trash import remove_originals
from tests.test_library import expo, upload


def test_explicit_original_removal_blocks_shared_records_and_is_resumable(
    signed_in, engine, settings
):
    expo_id = expo(signed_in)
    _, first = upload(signed_in, expo_id)
    _, other = upload(signed_in, expo_id)
    id = first["document"]["id"]
    asset_id = first["asset"]["id"]
    signed_in.delete(f"/api/v1/documents/{id}")
    preview = signed_in.get(f"/api/v1/documents/{id}/permanent-removal").json()
    assert preview["files"] == 1 and preview["blocked_file_ids"] == [asset_id]
    assert (
        signed_in.post(
            f"/api/v1/documents/{id}/permanent-removal", json={"confirmation": "DELETE"}
        ).status_code
        == 409
    )
    signed_in.delete(f"/api/v1/documents/{other['document']['id']}")
    assert (
        signed_in.post(
            f"/api/v1/documents/{id}/permanent-removal", json={"confirmation": "yes"}
        ).status_code
        == 422
    )
    response = signed_in.post(
        f"/api/v1/documents/{id}/permanent-removal", json={"confirmation": "DELETE"}
    )
    assert response.status_code == 202
    with Session(engine, expire_on_commit=False) as db:
        job = db.get(Job, UUID(response.json()["job_id"]))
        remove_originals(db, job, settings, pause=lambda _: nullcontext())
        remove_originals(db, job, settings, pause=lambda _: nullcontext())
    assert signed_in.get(f"/api/v1/assets/{asset_id}/original").status_code == 410
    assert signed_in.post(f"/api/v1/documents/{id}/restore").status_code == 410
    # Explicitly uploading identical bytes can restore them as a new appearance.
    _, again = upload(signed_in, expo_id)
    assert again["asset"]["id"] == asset_id
    assert signed_in.get(f"/api/v1/assets/{asset_id}/original").status_code == 200
