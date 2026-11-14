# Backup and restore

Backups contain the PostgreSQL records, relationships, corrections, notes, extraction revisions, settings and immutable originals. Provider credential data is excluded from the dump and saved separately as **non-secret, disabled** provider configuration. Previews, search chunks/vectors, models and temporary exports are omitted because they are rebuildable or temporary. The encryption key, database password and host ID remain outside the database/backup folders.

Set nightly time and retention in Settings → Backups. The default is 02:00 in `APP_TIMEZONE`, seven daily snapshots and four weekly snapshots. Daily/weekly retention keeps the latest snapshot for each retained period; unchanged originals use hard links within the backup filesystem. Deleting an expired snapshot never deletes a newer snapshot's hard-linked bytes or a library original. Keep this destination on a different physical disk. The dashboard warns if no successful backup exists, the latest attempt failed, or success is older than seven days.

Run one now through Settings or:

```sh
make backup
```

The worker uses PostgreSQL 18's `pg_dump --format=custom`, taken from the exact pinned database image. It first copies most immutable files, then takes an advisory write barrier shared by API mutations and processing jobs. Under that barrier it checks final file references and takes the database snapshot. Reads remain available. A manifest records original SHA-256 hashes and the dump checksum. Failed attempts keep previous complete snapshots.

Each complete snapshot is `BACKUP_DIR/snapshots/<backup-id>/` with `database.dump`, `assets/`, `providers-without-secrets.json` and `manifest.json`. The worker runs as the configured non-root UID; snapshot folders and files use private permissions. Keep backups private: they contain contact details, notes and the owner's password hash. Copy complete snapshots with a tool preserving hard links if you want to retain incremental space savings (`rsync -aH`).

## Restore to a new database

Prepare storage with the normal setup script; do not restore old volume markers over newly configured markers. Cache the models again if needed. Start the database and API containers so their tools are available. Use a complete snapshot from this server:

```sh
make restore BACKUP=/absolute/path/to/snapshots/BACKUP-ID DATABASE=expo_restored_check
```

The script refuses an existing destination database, verifies the dump and every original checksum, and refuses to overwrite a different existing original. It restores into a **new** database, applies migrations, recreates keyword chunks, and queues preview/vector rebuilding. Existing databases are preserved. An optional `--assets-dir` on `scripts/restore.py` selects another already-marked originals folder; configure its mount/path at cutover too.

Restoration clears login sessions, revokes agent tokens, disables cloud fallback and restores provider configuration **without credentials**. Password-free access follows your current `.env` setting. If password access is enabled, use the backed-up password or the server password-reset command. Reconnect/test providers and create fresh agent tokens. The app never needs a provider key to restore records or originals. If you separately retain an encryption key or credentials, protect them outside this backup set; the normal recovery path is to reconnect in Settings.

Review the restored record counts, original hashes, notes, sources and search before cutover. Then stop API/worker, set `DATABASE_NAME` to the verified new database in `.env`, adjust any storage paths/markers you deliberately changed, run `make check-storage` and start the stack. Do not erase the previous database until you have independently accepted the restored copy. Take a fresh backup after cutover.

For a test stack, pass its own `--env-file` and `--project-name` to `scripts/restore.py`. Use a NEW database name and clean marked originals/preview directories, then run a temporary app instance against those paths. Verify record counts, private notes, original checksums, search and a regenerated preview before accepting recovery. Never point the live worker at the recovery test database.

The restore path has been exercised on synthetic data, including checksum verification and refusal to overwrite an existing database. A successful test on your own hardware is still necessary. Backups in another folder on the same drive do not protect against drive failure; copy complete snapshots to independent storage.

A backup only covers data saved before its snapshot. Unsynced phone data remains on the phone; do not clear that queue during recovery. Original files explicitly removed through Trash retain tombstones; permanent removal does not purge old backup snapshots or existing exports.
