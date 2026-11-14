# Connect Hermes

Use the same trusted HTTPS `APP_URL` on your LAN and Tailscale. Hermes runs on your network; Expo Buddy adds no container, public port or second agent.

1. In Settings → Agent access, create a named token. Start with **Read library** only. Copy it once into a protected local config or environment variable; it cannot be retrieved later.
2. On the Hermes machine, edit `~/.hermes/config.yaml` (or that Hermes profile's config):

```yaml
mcp_servers:
  expo_buddy:
    url: "https://YOUR-CANONICAL-HOST/mcp"
    headers:
      Authorization: "Bearer ${EXPO_BUDDY_TOKEN}"
    tools:
      exclude: [create_export, add_note, add_tags, propose_field_change]
```

Supply `EXPO_BUDDY_TOKEN` to the Hermes process securely, or put the token directly in the config with file permissions `chmod 600`. Do not put it in a shared repository or chat. For Caddy's internal CA, install/trust its **public root certificate** on that machine, or add `ssl_verify: "/absolute/path/to/expo-root.crt"` under the server entry. Never disable certificate verification.

3. Run `/reload-mcp` in Hermes, or restart it. Ask: “Search Expo Buddy for solar mounting structures at my expo. Cite the document pages, and distinguish printed business roles from guesses.” Tool names are normalized by the installed Hermes version; include/exclude filters use the original names such as `search_library`.
4. Check Settings → Agent access → Agent activity. Revoke a token there to stop it immediately.

The current Hermes config reference was checked on 28 October 2026: [official reference](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/reference/mcp-config-reference.md). It supports URL-based HTTP servers, Authorization headers, `${VAR}`, tool filters and `/reload-mcp`.

Scopes: `read` retrieves records and source text; `notes` adds personal notes to search, reads and exports; `write` adds notes/tags and creates review proposals; `export` creates selected exports. Every token includes read. No scope allows deletion, merging, direct field replacement, provider/settings access, passwords or backups. A field proposal leaves the record unchanged until the owner accepts it in Review. Notes added by a token show the agent's name. Use a stable `client_uuid` when retrying `add_note`.

Search is local; the MCP server calls no cloud model. Whatever Hermes reads can leave your network if **Hermes uses a cloud AI model**. The owner chooses those scopes explicitly. Document/notes content is labelled untrusted data and never executed as instructions by this server.

The endpoint uses official `mcp==2.3.0`, `MCPServer`, and Streamable HTTP. It supports the legacy 2025-11-25 request path and the current 2026-07-28 request envelope. No slash redirect is needed. Requests are limited to 64 KiB. Each token runs up to 60 requests a minute; extra requests wait in a queue for the next free minute instead of failing. Only a queue more than 5 minutes deep returns 429 with `Retry-After`. Set your client's timeout high enough for queued requests; source text is paged at 12,000 characters, search at 50 results and returned data at 48,000 characters. Oversize results ask for a narrower request instead of silently losing a passage.

Tools: `list_expos`, `dashboard_summary`, `search_library`, `get_company`, `get_contact`, `get_document_text`, `list_review_queue`, `find_companies_by_capability`, `add_note`, `add_tags`, `propose_field_change`, `create_export`, `get_export_status`. Read resources: `expo://list`, `company://{id}`, `document://{id}/text`. Full document text is available with `get_document_text` and its `next_offset` cursor.

`create_export` accepts the same selection object as the REST API (see generated OpenAPI). An export belongs to its creating token. `get_export_status` returns a five-minute download ticket when ready; downloading also requires the **same** `Authorization: Bearer ...` header. Revocation or expiry blocks downloads too. Personal-note columns require the notes scope. ZIP originals and brochure text still contain their printed information even when a table field is deselected.

Use the official MCP Inspector with Streamable HTTP at the canonical `/mcp` endpoint and a temporary token to inspect tools/resources. Keep Inspector on localhost. This workspace verifies protocol behavior and the SDK client; connection to the owner's installed Hermes and physical network still needs to be exercised on that network.
