# Set up Expo Buddy

## Local Docker setup

Use Linux x86-64 with Docker Engine and Compose v2. Run commands from the project
root as a normal user with Docker access. `./scripts/docker.sh setup` runs the
standard-library setup utility inside the pinned Python container, with your UID
and GID. Python, Node and a GPU are not required on the host.

```sh
./scripts/docker.sh setup
./scripts/docker.sh models
./scripts/docker.sh models --kind embeddings
docker compose up -d --build --wait
```

Setup generates a database password, encryption key, host identity and `.env`.
It initializes six distinct storage folders with `.expo-buddy-volume` markers.
The app refuses missing or mismatched markers rather than silently writing to a
replacement directory. Existing `.env` files are preserved.

Local defaults: `https://localhost:8443`, loopback-only gateway, UTC timezone,
password-free access, cloud processing disabled, and all data under `.local/data`.
The local backup folder shares the data disk; copy snapshots to another physical
device for recovery from disk failure. Do not upload `.local` or `.secrets`.

Models download from pinned revisions before local OCR/semantic search can work.
You can start the app before downloading them to configure it, but processing will
report that models are missing. Ollama is optional and is not installed for you.

## HTTPS and phone access

Caddy creates a private CA for this installation. After the gateway starts, its
public root is `.secrets/caddy-data/caddy/pki/authorities/local/root.crt`.
Install/trust **only that public certificate** on your own computer/browser. On
Debian/Ubuntu, you can install it into the system trust store:

```sh
sudo install -m 644 .secrets/caddy-data/caddy/pki/authorities/local/root.crt /usr/local/share/ca-certificates/expo-buddy.crt
sudo update-ca-certificates
```

Some browsers use their own certificate store. `scripts/trust-local-ca.sh` supports
Linux Chromium's NSS store when `certutil` is installed. Never distribute the CA
private key or use disabled TLS verification as the permanent setup.

For a phone, choose one stable HTTPS hostname/address reachable from the phone,
configure that origin and the gateway binding, then trust the intended public CA
on the phone. Camera, installable-app and offline features require a secure origin.
See [LAN/Tailscale HTTPS](tailscale.md) and [phone installation](pwa.md).

Password-free mode gives anyone who reaches that address full access to your data
and provider settings. Keep it on a trusted LAN/VPN, or enable password access by
setting `PASSWORDLESS=false` and recreating the API/worker with Compose. Before
first use, password mode asks you to create a password. If you already opened
password-free mode, its account has a random inaccessible password; set your own
from the server before switching:

```sh
docker compose exec api python -m app.core.reset_password
```

No email service is required. Provider sign-in remains independent of app access.

## Custom storage and origin

For a fresh installation, copy `deploy/storage.example.json` to
`storage.local.json`, edit its paths, mount points, UID/GID and `app_url`, then run:

```sh
python3 scripts/setup.py --config storage.local.json
python3 scripts/check_storage.py
docker compose up -d --build --wait
```

This advanced path uses host Python 3.12. Configured mounts must exist and backups
must use a different filesystem. Choose separate physical backup hardware; a
filesystem check alone cannot prove disk independence. Local setup can also take
`--config storage.local.json` for a custom origin on a single-disk host.

Optional JSON keys `timezone` (for example `Europe/London`) and `passwordless`
(`true` or `false`) control those generated settings. A different `.env` is never
overwritten. Changing an existing origin requires reconfiguration and restarting
the stack; do not discard existing storage markers or secret files.

See [.env.example](../.env.example) for limits, ports and directories. Defaults
allow images up to 100 MiB and PDFs up to 400 MiB / 200 pages. Keep at least 5 GiB
free for originals, plus image/model, backup and export space. API and database
ports stay private; only Caddy and the loopback-only OAuth callback are published.

## Optional AI providers

In Settings, configure your existing Ollama server and an exact installed model
name. A container reaches a host Ollama at `host.docker.internal` if that server's
binding/firewall permits it; `localhost` inside the container is the container.
Do not expose Ollama publicly. The model choice and test result are shown separately.

[ChatGPT plan sign-in](chatgpt-connection.md) works through a loopback callback on
the server PC, or the protected helper on another computer. Eligibility, consent
and account limits apply. OpenRouter requires your own key and a positive budget.
Enable cloud processing explicitly only when you want printed text and capture
context sent. Existing personal notes are excluded; image checks use local Ollama.

## Back up and update

For an existing installation, keep its working configuration, markers and secret
files. A fresh checkout generates a new installation identity. Move data through
the backup/restore procedure into a new database and correctly marked storage;
do not replace volume markers or copy a fresh `.env` over the live installation.

Set the schedule in Settings, run a backup and practice a restore to a new database.
Follow [backup and restore](backup-restore.md) and [operations](operations.md).
Never delete `.secrets`: it holds the identity/encryption material needed by the
current installation. Never replace a working installation with a fresh `.env`.
