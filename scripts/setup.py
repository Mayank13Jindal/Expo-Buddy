#!/usr/bin/env python3
"""Explicit first-time host setup. Runtime services never create volume markers."""

import argparse
import base64
import json
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from storage_config import LABELS, MARKER, NAMES


def write_private(path: Path, content: str, uid: int, gid: int) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    if os.getuid() == 0:
        os.chown(path, uid, gid)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", "--development", dest="development", action="store_true", help="Single-host storage with a loopback-only gateway")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--config", type=Path, help="See deploy/storage.example.json")
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    project = args.project.resolve()
    env_path = project / ".env"
    if env_path.exists():
        print(".env already exists; nothing changed. Run make check-storage.")
        return 0
    if not args.development and not args.config:
        parser.error("Use --config for custom storage, or --local for single-host storage")
    config = json.loads(args.config.read_text()) if args.config else {}
    if not isinstance(config.get("passwordless", False), bool):
        parser.error("passwordless must be true or false")
    uid, gid = int(config.get("uid", os.getuid())), int(config.get("gid", os.getgid()))
    if uid == 0 or gid == 0:
        parser.error("Choose a non-root uid and gid in the configuration")
    if os.getuid() != 0 and (uid != os.getuid() or gid != os.getgid()):
        parser.error("Run as the requested uid/gid or use sudo for initial ownership setup")
    root = (args.data_root or project / ".local/data").resolve()
    paths = {
        name: Path(config.get("paths", {}).get(name, root / LABELS[name])).absolute()
        for name in NAMES
    }
    if len(set(paths.values())) != len(NAMES):
        parser.error("Each storage folder must be distinct")
    for one in paths.values():
        for other in paths.values():
            if one != other and one.is_relative_to(other):
                parser.error("Storage folders cannot be inside one another")
        if any(char in str(one) for char in "\n\r$#'\""):
            parser.error("Storage paths contain unsupported .env characters")
    app_url = config.get("app_url", "https://localhost:8443").rstrip("/")
    url = urlsplit(app_url)
    if url.scheme != "https" or not url.hostname or url.path or url.query or url.fragment:
        parser.error("app_url must be one HTTPS origin, without a path")
    if url.username or url.password:
        parser.error("app_url must not contain credentials")
    hostname = f"[{url.hostname}]" if ':' in url.hostname else url.hostname
    app_url = f"https://{hostname}" + (f":{url.port}" if url.port and url.port != 443 else '')
    url = urlsplit(app_url)
    mounts = config.get("mounts", {})
    for name in NAMES:
        if mount := mounts.get(name):
            mount_path = Path(mount).resolve()
            if not os.path.ismount(mount_path) or not paths[name].is_relative_to(mount_path):
                parser.error(f"Expected mount is unavailable for {name}")
    # Verify existing folders before creating anything. Never claim unrelated data.
    for name, path in paths.items():
        if path.is_symlink():
            parser.error(f"Use a real directory for {name}")
        if path.exists() and any(path.iterdir()) and not (path / MARKER).is_file():
            parser.error(f"Refusing to initialise a nonempty unmarked folder: {name}")
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True, mode=0o750)
        if os.getuid() == 0:
            os.chown(path, uid, gid)
    shared_backup = paths["ASSETS"].stat().st_dev == paths["BACKUP"].stat().st_dev
    if shared_backup and not args.development:
        parser.error("Backups must be on a different physical disk; check mounts")
    volume_ids = {}
    for name, path in paths.items():
        marker = path / MARKER
        if marker.exists():
            if marker.is_symlink():
                parser.error(f"Invalid marker for {name}")
            volume_ids[name] = str(UUID(marker.read_text().strip()))
        else:
            volume_ids[name] = str(uuid4())
            write_private(marker, volume_ids[name] + "\n", uid, gid)
    secret_dir = project / ".secrets"
    secret_dir.mkdir(mode=0o700, exist_ok=True)
    if os.getuid() == 0:
        os.chown(secret_dir, uid, gid)
    for filename, content in {
        "database_password": secrets.token_urlsafe(48),
        "encryption_key": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "host_id": str(uuid4()),
    }.items():
        if not (secret_dir / filename).exists():
            write_private(secret_dir / filename, content + "\n", uid, gid)
    for name in ("caddy-data", "caddy-config"):
        path = secret_dir / name
        path.mkdir(mode=0o700, exist_ok=True)
        if os.getuid() == 0:
            os.chown(path, uid, gid)
    values = {
        "APP_URL": app_url, "APP_HOST": url.hostname, "APP_AUTHORITY": url.netloc,
        "APP_UID": str(uid), "APP_GID": str(gid), "APP_TIMEZONE": config.get("timezone", "UTC"),
        "PASSWORDLESS": str(config.get("passwordless", False)).lower(),
        "GATEWAY_BIND": "127.0.0.1" if args.development else "0.0.0.0",
        "GATEWAY_HTTPS_PORT": str(url.port or 443), "GATEWAY_HTTP_PORT": "8080",
        "CADDY_TLS": "internal", "SECRETS_DIR": str(secret_dir),
        "ALLOW_SHARED_BACKUP_DISK": str(args.development).lower(),
        "ASSETS_FREE_FLOOR_BYTES": str(5 * 1024**3), "STORAGE_CHECK_SECONDS": "30",
        "IMAGE_LIMIT_BYTES": str(100 * 1024**2), "PDF_LIMIT_BYTES": str(400 * 1024**2),
        "PDF_PAGE_LIMIT": "200", "GATEWAY_BODY_LIMIT": str(404 * 1024**2),
        "OLLAMA_URL": "", "OLLAMA_MODEL": "",
    }
    for name in NAMES:
        values[f"{name}_DIR"] = str(paths[name])
        values[f"{name}_VOLUME_ID"] = volume_ids[name]
        values[f"{name}_MOUNT"] = mounts.get(name, "")
    write_private(env_path, "\n".join(f"{key}='{value}'" for key, value in values.items()) + "\n", uid, gid)
    print("Created configuration, private secret files and storage markers.")
    if args.development:
        print("Local storage shares one disk. Copy backups to another physical device for drive-failure recovery.")
    print("Next: download models, then docker compose up -d --build --wait")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as error:
        print(f"Setup failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None

