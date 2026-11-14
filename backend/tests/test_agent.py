import json
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.agent import APIToken
from app.db.exports import Export
from app.exports.package import build
from tests.test_library import expo, upload


def token(web, scopes=None):
    r = web.post(
        "/api/v1/settings/agent-tokens", json={"name": "Fake Hermes", "scopes": scopes or ["read"]}
    )
    assert r.status_code == 201, r.text
    value = r.json()
    assert value["token"] not in web.get("/api/v1/settings/agent-tokens").text
    return value


def rpc(web, secret, method="tools/list", params=None):
    return web.post(
        "/mcp",
        headers={
            "Authorization": "Bearer " + secret,
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )


def call(web, secret, tool, arguments=None):
    response = rpc(web, secret, "tools/call", {"name": tool, "arguments": arguments or {}})
    assert response.status_code == 200, response.text
    return response.json()["result"]


def test_mcp_missing_revoked_scopes_and_proposals(signed_in):
    assert signed_in.post("/mcp", json={}).status_code == 401
    read = token(signed_in)
    tools = rpc(signed_in, read["token"]).json()["result"]["tools"]
    assert {"search_library", "propose_field_change", "get_document_text"} <= {
        row["name"] for row in tools
    }
    company = signed_in.post(
        "/api/v1/companies", json={"fields": {"display_name": "FICTIONAL Original Name"}}
    ).json()
    denied = call(
        signed_in,
        read["token"],
        "add_note",
        {"entity_type": "company", "entity_id": company["id"], "text": "Fictional agent note"},
    )
    assert denied.get("isError") is True and "write scope" in json.dumps(denied)
    write = token(signed_in, ["read", "write"])
    proposed = call(
        signed_in,
        write["token"],
        "propose_field_change",
        {
            "entity_type": "company",
            "entity_id": company["id"],
            "field": "display_name",
            "value": "FICTIONAL Proposed Name",
        },
    )
    assert not proposed.get("isError"), proposed
    assert (
        signed_in.get(f"/api/v1/companies/{company['id']}").json()["display_name"]
        == "FICTIONAL Original Name"
    )
    assert (
        signed_in.get("/api/v1/review").json()["proposals"][0]["proposed_value"]
        == "FICTIONAL Proposed Name"
    )
    signed_in.delete(f"/api/v1/settings/agent-tokens/{read['id']}")
    assert rpc(signed_in, read["token"]).status_code == 401
    assert any(
        row["status"] == "denied" for row in signed_in.get("/api/v1/settings/agent-activity").json()
    )


def test_notes_not_used_in_mcp_search_or_company_without_scope(signed_in, monkeypatch):
    import httpx

    def offline(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx.Client, "post", offline)
    _, doc = upload(signed_in, expo(signed_in))
    company = signed_in.post(
        "/api/v1/companies", json={"fields": {"display_name": "FICTIONAL Company"}}
    ).json()
    signed_in.post(
        f"/api/v1/documents/{doc['document']['id']}/attach-company",
        json={"company_id": company["id"]},
    )
    signed_in.post(
        "/api/v1/notes",
        json={"document_id": doc["document"]["id"], "text": "FAKE secret orchid queue"},
    )
    read = token(signed_in)
    hidden = call(
        signed_in,
        read["token"],
        "search_library",
        {"query": "secret orchid queue", "all_expos": True},
    )
    assert "FAKE secret orchid queue" not in json.dumps(hidden)
    details = call(signed_in, read["token"], "get_company", {"id": company["id"]})
    assert "FAKE secret orchid queue" not in json.dumps(details)
    notes = token(signed_in, ["read", "notes"])
    visible = call(
        signed_in,
        notes["token"],
        "search_library",
        {"query": "secret orchid queue", "all_expos": True},
    )
    assert "FAKE secret orchid queue" in json.dumps(visible)
    resources = rpc(signed_in, read["token"], "resources/list").json()
    assert "expo://list" in json.dumps(resources)


def test_rate_limit_and_expiring_token_bound_export_download(signed_in, engine, settings):
    _, saved = upload(signed_in, expo(signed_in))
    export_token = token(signed_in, ["read", "export"])
    denied = call(
        signed_in,
        export_token["token"],
        "create_export",
        {
            "selection": {
                "scope": "all",
                "tables": ["documents"],
                "fields": {"documents": ["notes"]},
                "format": "xlsx",
                "allow_unreviewed": True,
            }
        },
    )
    assert denied.get("isError") and "notes scope" in json.dumps(denied)
    result = call(
        signed_in,
        export_token["token"],
        "create_export",
        {
            "selection": {
                "scope": "all",
                "tables": ["documents"],
                "fields": {"documents": ["title"]},
                "format": "xlsx",
                "allow_unreviewed": True,
            }
        },
    )
    assert not result.get("isError"), result
    export_id = result["structuredContent"]["data"]["export_id"]
    with Session(engine) as db:
        build(db, db.get(Export, UUID(export_id)), settings)
    status = call(signed_in, export_token["token"], "get_export_status", {"id": export_id})[
        "structuredContent"
    ]["data"]
    url = status["download_url"]
    assert signed_in.get(url).status_code == 401
    other = token(signed_in, ["read", "export"])
    assert (
        signed_in.get(url, headers={"Authorization": "Bearer " + other["token"]}).status_code == 403
    )
    assert (
        signed_in.get(url, headers={"Authorization": "Bearer " + export_token["token"]}).status_code
        == 200
    )
    with Session(engine) as db:
        row = db.get(APIToken, UUID(export_token["id"]))
        row.calls = 60
        db.commit()
    assert rpc(signed_in, export_token["token"], "ping").status_code == 429
    assert signed_in.get(f"/api/v1/assets/{saved['asset']['id']}/original").status_code == 200


def test_modern_mcp_envelope_and_context(signed_in):
    from mcp.types import LATEST_PROTOCOL_VERSION

    read = token(signed_in)
    response = signed_in.post(
        "/mcp",
        headers={
            "Authorization": "Bearer " + read["token"],
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
            "Mcp-Method": "tools/call",
            "Mcp-Name": "list_expos",
        },
        json={
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "list_expos",
                "arguments": {},
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": LATEST_PROTOCOL_VERSION,
                    "io.modelcontextprotocol/clientCapabilities": {},
                },
            },
        },
    )
    assert response.status_code == 200, response.text
    assert not response.json()["result"].get("isError"), response.text
