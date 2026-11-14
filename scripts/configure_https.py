#!/usr/bin/env python3
"""Configure standard-port LAN HTTPS or trusted Tailscale Serve HTTPS on the server."""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from storage_config import read_env


def run(command, *, cwd):
    return subprocess.run(
        command, cwd=cwd, check=True, capture_output=True, text=True, timeout=240
    ).stdout


def origin(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Use one HTTPS address without a path or credentials.")
    if parsed.port not in (None, 443):
        raise ValueError(
            "Use standard HTTPS port 443 (omit the port from the address)."
        )
    host = parsed.hostname
    if not re.fullmatch(r"[a-zA-Z0-9.:-]+", host):
        raise ValueError("Invalid hostname.")
    authority = f"[{host}]" if ":" in host else host
    return f"https://{authority}", host, authority


def edit_env(content, values):
    lines = content.splitlines()
    for key, value in values.items():
        replacement = f"{key}='{value}'"
        matches = [
            i for i, line in enumerate(lines) if line.partition("=")[0].strip() == key
        ]
        if len(matches) > 1:
            raise ValueError(
                f"Remove duplicate {key} entries before configuring HTTPS."
            )
        if matches:
            lines[matches[0]] = replacement
        else:
            lines.append(replacement)
    return "\n".join(lines) + "\n"


def override(project, mode, backend_port):
    # !override replaces both default published ports; no HTTP LAN exposure in proxy mode.
    ports = (
        [f"127.0.0.1:{backend_port}:8080"]
        if mode == "tailscale"
        else ["0.0.0.0:443:8443"]
    )
    caddyfile = (
        project / "deploy" / ("Caddyfile.proxy" if mode == "tailscale" else "Caddyfile")
    )
    return (
        "services:\n  gateway:\n    ports: !override\n"
        + "".join(f"      - {json.dumps(port)}\n" for port in ports)
        + "    volumes:\n      - type: bind\n        source: "
        + json.dumps(str(caddyfile))
        + "\n        target: /etc/caddy/Caddyfile\n        read_only: true\n"
    )


def private_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("lan", "tailscale"), required=True)
    parser.add_argument(
        "--url",
        help="LAN address, e.g. https://192.168.1.100; Tailscale hostname is discovered automatically",
    )
    parser.add_argument(
        "--project", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--backend-port", type=int, default=8080)
    parser.add_argument(
        "--compose-file",
        action="append",
        default=[],
        help="Additional existing Compose override; repeat if needed",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the displayed mode and restart API, worker and gateway",
    )
    args = parser.parse_args()
    project = args.project.resolve()
    if not 1024 <= args.backend_port <= 65535:
        parser.error("Choose an unprivileged backend port from 1024 to 65535.")
    env_path, override_path = project / ".env", project / "deploy/https.local.yml"
    env = read_env(env_path)
    serve_command = None
    if args.mode == "tailscale":
        status = json.loads(run(["tailscale", "status", "--json"], cwd=project))
        if status.get("BackendState") != "Running":
            raise ValueError(
                "Install Tailscale and sign this server into your tailnet first."
            )
        hostname = status.get("Self", {}).get("DNSName", "").rstrip(".")
        if not hostname.endswith(".ts.net"):
            raise ValueError(
                "Enable MagicDNS and HTTPS certificates in the Tailscale admin console first."
            )
        url, host, authority = origin("https://" + hostname)
        if args.url and origin(args.url)[0] != url:
            raise ValueError("The address must match this server's Tailscale hostname.")
        current = json.loads(
            run(["tailscale", "serve", "status", "--json"], cwd=project)
        )
        handlers = (
            current.get("Web", {}).get(authority + ":443", {}).get("Handlers", {})
        )
        expected = f"http://127.0.0.1:{args.backend_port}"
        if (handlers and handlers != {"/": {"Proxy": expected}}) or (
            current.get("TCP", {}).get("443") and not handlers
        ):
            raise ValueError(
                "Tailscale Serve already hosts another app on port 443; choose a separate server or adjust that configuration first."
            )
        serve_command = ["tailscale", "serve", "--bg", "--https=443", "--yes", expected]
    else:
        if not args.url:
            parser.error("LAN mode requires --url https://YOUR-LAN-IP")
        url, host, authority = origin(args.url)
    values = {
        "APP_URL": url,
        "APP_HOST": host,
        "APP_AUTHORITY": authority,
        "GATEWAY_HTTPS_PORT": "443",
        "GATEWAY_BIND": "0.0.0.0",
        "CADDY_TLS": "internal",
    }
    content = edit_env(env_path.read_text(), values)
    generated = override(project, args.mode, args.backend_port)
    print(f"Current address: {env['APP_URL']}\nProposed address: {url}")
    print(
        "HTTPS: standard port 443. "
        + (
            "Trusted Tailscale certificate; connect phones to the same tailnet. No Android CA installation."
            if args.mode == "tailscale"
            else "Private CA; phones must trust the public CA certificate. Reserve the server's LAN IP."
        )
    )
    if env["APP_URL"].rstrip("/") != url:
        print(
            "Before changing address: finish syncing each phone's offline queue at the old address. Browser queues stay with their original address."
        )
    print("Compose override: deploy/https.local.yml (automatically used by Make).")
    if not args.apply:
        print(
            "Preview only. Run the same command with --apply on the server to activate it."
        )
        return 0
    base = ["docker", "compose", "-f", "docker-compose.yml"]
    for candidate in [
        "docker-compose.override.yml",
        ".local/compose.proxy.yml",
        *args.compose_file,
    ]:
        if (project / candidate).is_file():
            base += ["-f", candidate]
    previous_override = override_path.read_text() if override_path.exists() else None
    previous_env = env_path.read_text()
    private_write(project / ".env.before-https", previous_env)
    if previous_override is not None:
        private_write(project / ".local/https-override.before", previous_override)
    active = base + ["-f", "deploy/https.local.yml"]
    try:
        private_write(env_path, content)
        private_write(override_path, generated)
        run(active + ["config", "--quiet"], cwd=project)
        run(
            active
            + [
                "up",
                "-d",
                "--no-build",
                "--wait",
                "--wait-timeout",
                "180",
                "api",
                "worker",
                "gateway",
            ],
            cwd=project,
        )
        if serve_command:
            run(serve_command, cwd=project)
    except Exception:
        private_write(env_path, previous_env)
        if previous_override is None:
            override_path.unlink(missing_ok=True)
        else:
            private_write(override_path, previous_override)
        try:
            run(
                (active if previous_override is not None else base)
                + ["up", "-d", "--no-build", "api", "worker", "gateway"],
                cwd=project,
            )
        except (OSError, subprocess.SubprocessError):
            print(
                "Previous configuration restored. Restart services with make up.",
                file=sys.stderr,
            )
        raise
    print(f"Configured. Open {url} on your phone and sign in again.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
    except (OSError, subprocess.SubprocessError, KeyError):
        print(
            "HTTPS configuration could not finish. Check Docker access, Tailscale status/HTTPS permissions and whether port 443 is in use. Existing configuration is retained or restored. Run without --apply to preview.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
