# Expo Buddy

A self-hosted home for the people, companies and ideas you collect at expos.
Scan visiting cards and brochures, check extracted details beside the originals,
keep private notes, and export the contacts you want to follow up with.

## What it does

- Photo/PDF capture, local CPU OCR and an offline phone capture queue.
- Companies and people, source evidence, manual corrections and field-by-field review.
- Keyword search with optional local semantic search.
- Excel, CSV, vCard and ZIP exports with review warnings.
- Optional Ollama, ChatGPT plan sign-in and OpenRouter processing.
- Backups, restore to a new database, and scoped MCP access for agents.

Personal notes remain local to your server. Optional cloud extraction sends printed
text and explicitly entered capture/reprocessing context. Optional image checks use
local Ollama. No provider account is needed to browse, edit or search your library.

## Run with Docker

Supported host: **Linux x86-64**, Docker Engine with Compose v2, and a POSIX shell.
Allow several GB for container images/model downloads and at least 5 GiB of free
space for captures. A GPU is optional. Python and Node run inside Docker.

From this repository's root, as your normal user with Docker access:

```sh
./scripts/docker.sh setup
./scripts/docker.sh models
./scripts/docker.sh models --kind embeddings
docker compose up -d --build --wait
```

Setup creates `.env`, private secrets and marked storage under `.local/data`.
It does not replace existing configuration. Model downloads are pinned and may
take time; do not interrupt the first download. The stack contains PostgreSQL,
the API, the worker and Caddy serving the built web app.

Open **https://localhost:8443** after trusting your installation's public CA at
`.secrets/caddy-data/caddy/pki/authorities/local/root.crt`. See
[HTTPS and phone setup](docs/setup.md#https-and-phone-access). Keep the CA's
private key private; do not disable certificate verification.

The default setup binds to this computer and opens without an app password.
Provider sign-in is separate. Password-free access gives anyone who can reach
the app full access, including settings. For shared networks, set
`PASSWORDLESS=false` in `.env` and recreate the stack. If you have already used
password-free mode, first set a password with `docker compose exec api python -m app.core.reset_password`. Cloud processing starts off.

```sh
docker compose ps                 # service health
docker compose logs --tail=100   # recent logs
docker compose stop             # stop; keep saved data
docker compose up -d --wait      # start again
```

[Setup and configuration](docs/setup.md) explains phone access, storage, providers
and backups. [.env.example](.env.example) documents configuration; setup generates
the actual values and secrets. [Recovery instructions](docs/backup-restore.md)
explain how to restore into a new database before cutover.

## Project layout

```text
backend/       FastAPI, database migrations, processing and tests
frontend/      React/TypeScript web app and offline capture
scripts/       Setup, models, storage checks and restore utilities
deploy/        Caddy and Docker support
examples/      Fictional sample exports
docs/          Setup, providers, operation and recovery
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for development and tests,
[SECURITY.md](SECURITY.md) for private reports, and [the GitHub guide](docs/github.md)
for publishing your copy. This project is licensed under [MIT](LICENSE).
Dependencies and model weights retain their own [licenses and notices](docs/NOTICES.md).

## Current limits

Expo Buddy is a personal, single-owner app. OCR and AI output need human review;
syntax validation does not prove a number belongs to a person. Phone storage is
not a backup: keep unsynced captures until the server confirms they are saved.
Real iPhone/Safari behavior, other CPU architectures and every provider/account
combination have not been verified. Windows/macOS Docker Desktop are not yet
supported by the host storage setup.
