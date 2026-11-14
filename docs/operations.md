# Operate the library

Use `make up`, `make stop` and `docker compose ps`. Production Compose builds the pinned application dependencies into images; no development source bind mounts are needed. Only the gateway publishes ports. Health checks cover DB/schema, worker heartbeat and all marked storage folders; provider outages are shown separately and do not make the whole app unhealthy.

Settings → System health shows job states, cached models, free space and recent bounded error reasons. Dashboard panels update through SSE, with polling recovery. Uploads stop below the configured originals free-space floor. Never bypass a missing-drive marker or create a replacement folder to make a failed mount look healthy.

To move storage: stop API/worker (or `make stop`), copy the chosen directory with `rsync -aH`, retain its marker, update its path and expected mount in `.env`, run `make check-storage`, then start again. Stored asset paths are relative, so DB edits are unnecessary. Previews and models can be rebuilt/downloaded instead of copied. PostgreSQL's parent mount contains `18/docker`; never mount an old PostgreSQL major-version directory into this image.

Back up before updating. Save the current code version, `.env` and image IDs. Update to a reviewed version, build the pinned images (`docker compose build --pull`), then start with `--wait`; the API applies Alembic migrations before serving. Check health, a source original, a note and search. For rollback, stop API/worker, restore the pre-update backup into a new database, return to the matching code/images, and change `DATABASE_NAME` to that restored database. Do not run an old app against an incompatible newer schema or blindly downgrade PostgreSQL. [Backup/restore details](backup-restore.md).

Password reset is a server command; it does not use email:

```sh
make reset-password
```

Enter the new password at the terminal. Other browser sessions are invalidated. Ten failed logins trigger a temporary lockout; reset clears it. Keys and tokens belong in Settings or protected files, never in shell history, source code, logs or chat.

Processing resumes from leased jobs after restart. CPU work and AI calls have separate single-task pools. Files are durably saved before processing is queued. With providers off, grouping/OCR/notes/keyword search remain available; AI waits with a reason. Reprocessing preserves user corrections and creates proposals for conflicting values. Ordinary new captures auto-confirm for processing. Explicit booth/front/back groups wait for confirmation; reprocessing explicitly confirms the selected document.

Use Trash to restore records. Permanent file removal requires an exact `DELETE` confirmation and displays file count/size. It is blocked when another active record uses the same original or a retained source version. Removal is a leased, resumable job with a durable tombstone. Record history, old backups and already generated exports can retain information; file removal is not an assertion that every historical copy was erased.

Troubleshooting:

- **Can't install/open on phone:** use the canonical trusted HTTPS address, check the certificate and keep Tailscale on. A different origin has a different queue.
- **Phone queue won't sync:** keep the app open, sign in, check its item error and Retry. Keep unsaved blobs; never clear browser storage to fix connectivity.
- **OCR/search waiting:** check model cache, drive markers and free space. Run the pinned model downloader from setup. Keyword search works while vectors warm up.
- **AI waiting:** check provider enable/model/test status, cooldown, cloud opt-in and OpenRouter cap. An Ollama cloud model requires cloud permission even if reached through a LAN Ollama address.
- **Missing original:** inspect the actual originals drive/mount. The app will not silently redirect writes to another disk.
- **Backup failed:** check the backup drive, capacity and database access; previous complete snapshots are preserved. Run a fresh backup after correcting it.
- **Docker disk full:** inspect image/build-cache usage. Remove only known unused images/cache after replacement containers are healthy. Never delete data volumes/directories or originals as build cleanup.

Logs are bounded and API access logging is disabled. Application JSON logs emit event identifiers rather than request bodies, provider keys or full OCR text. Keep any diagnostics you export private. Files use content sniffing, SHA-256 checks and safe UUID paths; PDF content is rendered/extracted as data and served as an authenticated attachment. CSP, frame denial, no-sniff, HSTS, CSRF/origin checks, secure cookies, JSON body caps and scoped/rate-limited MCP tokens are enabled.

## Browser fetch error after a deployment

The gateway exposes HTTPS on the configured host port (8443 locally, often 443 on a LAN) while Caddy listens on 8443
inside Docker. HTTP/3 is disabled because UDP/8443 is not a published endpoint;
`Alt-Svc: clear` removes stale browser advertisements for that internal port.
HTTP/1.1 and HTTP/2 remain available with normal certificate verification.

If a browser can open `/api/v1/health` but a cached app shows a network error,
reload the main page with Ctrl+Shift+R, or close all app tabs and reopen the same
canonical URL. Do not clear site data to troubleshoot an unsynced capture queue.
