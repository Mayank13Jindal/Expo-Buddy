#!/usr/bin/env python3
"""Restore only into a NEW PostgreSQL database, preserving every existing database."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from storage_config import MARKER, read_env

ROOT = Path(__file__).resolve().parents[1]


def hash_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def inside(root, relative):
    result = (root / relative).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError('Backup contains an invalid relative path')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env', help='Configuration for the destination stack')
    parser.add_argument('--project-name', help='Explicit Compose project, required for isolated restore drills')
    parser.add_argument('backup', type=Path, help='Complete snapshot directory, containing manifest.json')
    parser.add_argument('--assets-dir', type=Path, help='Optional clean, marked originals directory on this host')
    parser.add_argument('--database', default='expo_restored_' + datetime.now(UTC).strftime('%Y%m%d_%H%M%S'))
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', args.database):
        parser.error('Use a simple lowercase database name')
    config = read_env(args.env_file.resolve())
    assets = args.assets_dir or Path(config['ASSETS_DIR'])
    if not assets.is_dir() or (assets / MARKER).is_symlink() or (assets / MARKER).read_text().strip() != config['ASSETS_VOLUME_ID']:
        raise ValueError('Originals drive is missing or has the wrong marker; nothing restored')
    snapshot = args.backup.resolve()
    manifest = json.loads((snapshot / 'manifest.json').read_text())
    dump = inside(snapshot, manifest['database']['file'])
    if manifest['version'] != 1 or hash_file(dump) != manifest['database']['sha256']:
        raise ValueError('The database dump checksum does not match')
    for item in manifest['assets']:
        source, destination = inside(snapshot / 'assets', item['path']), inside(assets, item['path'])
        if not re.fullmatch(r'[a-f0-9]{64}', item['sha256']) or hash_file(source) != item['sha256']:
            raise ValueError('An original checksum does not match; nothing imported into the database')
        if destination.exists() and hash_file(destination) != item['sha256']:
            raise ValueError('An existing original differs. Use clean storage; nothing will be overwritten')
    compose = ['docker', 'compose', '--env-file', str(args.env_file.resolve())]
    if args.project_name:
        compose += ['--project-name', args.project_name]
    override = ROOT / '.local/compose.proxy.yml'
    if override.exists() and args.env_file.resolve() == (ROOT / '.env').resolve():
        compose += ['-f', str(ROOT / 'docker-compose.yml'), '-f', str(override)]
    def run(args, **kwargs):
        return subprocess.run(compose + args, cwd=ROOT, check=True, **kwargs)
    existing = subprocess.check_output(compose + ['exec', '-T', 'db', 'psql', '-U', 'expo', '-d', 'postgres', '-Atc', f"SELECT datname FROM pg_database WHERE datname='{args.database}'"], cwd=ROOT, text=True).strip()
    if existing:
        raise ValueError('Destination database already exists. Choose a NEW --database; existing databases are never overwritten')
    run(['exec', '-T', 'db', 'psql', '-U', 'expo', '-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-c', f'CREATE DATABASE "{args.database}"'])
    with dump.open('rb') as stream:
        run(['exec', '-T', 'db', 'pg_restore', '-U', 'expo', '--dbname', args.database, '--no-owner', '--no-acl', '--exit-on-error'], stdin=stream)
    for item in manifest['assets']:
        source, destination = inside(snapshot / 'assets', item['path']), inside(assets, item['path'])
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
            with source.open('rb') as incoming, destination.open('xb') as output:
                shutil.copyfileobj(incoming, output, 1024 * 1024)
                output.flush()
                import os
                os.fsync(output.fileno())
    run(['exec', '-T', '-e', f'DATABASE_NAME={args.database}', 'api', 'alembic', 'upgrade', 'head'])
    # Feed redacted provider configuration through stdin; no credentials or Docker socket enter the app.
    redacted = json.loads((snapshot / 'providers-without-secrets.json').read_text())
    code = 'import json,sys; from sqlalchemy.orm import Session; from app.core.config import Settings; from app.db.session import build_engine; from app.core.restore_finalize import finalize; db=Session(build_engine(Settings())); finalize(db,json.load(sys.stdin)); db.close(); print("Restore finalization complete")'
    run(['exec', '-T', '-e', f'DATABASE_NAME={args.database}', 'api', 'python', '-c', code], input=json.dumps(redacted).encode())
    print(f'Restored and verified {len(manifest["assets"])} originals into NEW database {args.database}.')
    print(f'For cutover: stop api/worker, set DATABASE_NAME={args.database} in .env, then start the stack. The current database was preserved.')
    if args.assets_dir:
        print(f'Also set ASSETS_DIR={assets} and verify its mount/marker before cutover.')
    print('Reconnect providers, issue fresh agent tokens, keep the existing phone queue, and run a new backup.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        raise SystemExit('Restore stopped. Check the backup manifest, drive markers and database destination. Existing databases and originals were preserved.') from None
