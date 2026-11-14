#!/usr/bin/env python3
"""Read-only HTTPS/port checks. Run on the library server or another computer."""

import argparse
import socket
import ssl
from pathlib import Path
from urllib.parse import urlsplit

from storage_config import read_env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="HTTPS origin; defaults to APP_URL from .env")
    parser.add_argument(
        "--project", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    env = read_env(args.project / ".env") if (args.project / ".env").exists() else {}
    url = urlsplit(args.url or env.get("APP_URL", ""))
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        parser.error("Supply an HTTPS address or configure APP_URL.")
    port = url.port or 443
    print(f"Address: https://{url.netloc}; HTTPS port: {port}")
    if port != 443:
        print(
            "This is a nonstandard port. Your previous phone connection worked on 443."
        )
    try:
        with socket.create_connection((url.hostname, port), timeout=5):
            pass
    except OSError:
        print(
            "Connection failed before certificate checking. Check binding, firewall, address and that both devices can reach this network."
        )
        return 1
    print("TCP port reachable.")
    contexts = [("System/browser CA store", ssl.create_default_context())]
    root = (
        Path(env.get("SECRETS_DIR", args.project / ".secrets"))
        / "caddy-data/caddy/pki/authorities/local/root.crt"
    )
    if root.is_file():
        contexts.append(
            (
                "Library private CA (must be installed separately on Android)",
                ssl.create_default_context(cafile=str(root)),
            )
        )
    for label, context in contexts:
        try:
            with (
                socket.create_connection((url.hostname, port), timeout=5) as connection,
                context.wrap_socket(connection, server_hostname=url.hostname) as secure,
            ):
                certificate = secure.getpeercert()
                print(
                    f"{label}: verified hostname and certificate; expires {certificate.get('notAfter', 'unknown')}."
                )
                host = url.netloc.encode("ascii")
                secure.sendall(
                    b"GET /api/v1/health HTTP/1.1\r\nHost: "
                    + host
                    + b"\r\nConnection: close\r\n\r\n"
                )
                status = (
                    secure.recv(4096)
                    .split(b"\r\n", 1)[0]
                    .decode("ascii", errors="replace")
                )
                print("Health endpoint: " + status)
                return 0 if " 200 " in status else 1
        except ssl.SSLCertVerificationError:
            print(label + ": certificate not trusted or hostname incorrect.")
        except (OSError, UnicodeError):
            print(label + ": TLS or health request failed.")
    print(
        "A private IP needs a trusted private CA. A Tailscale HTTPS hostname can use a publicly trusted certificate. See docs/tailscale.md."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
