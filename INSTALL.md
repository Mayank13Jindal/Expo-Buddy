# Install Expo Buddy

Pick one way:

- **[AI-assisted install](#ai-assisted-install)**: let an AI coding agent do it for you.
- **[Easy install](#easy-install)**: copy and paste commands in 6 steps.
- **[Manual install](#manual-install)**: every step explained, for full control.

**You need:** a Linux x86-64 computer (Ubuntu or Debian is easiest), about 15 GB free
disk space, Git, curl and an internet connection. Builds and downloads can take longer
on slower computers or connections. Windows and macOS are not supported yet.

---

## AI-assisted install

Use an AI coding agent that can run commands on your computer, such as Claude Code,
Cursor or Codex. Open it inside an empty folder, then copy and paste this prompt:

````text
Please install Expo Buddy on this computer from
https://github.com/Mayank13Jindal/Expo-Buddy and get it running.

Steps:
1. Check this is Linux x86-64 with at least 15 GB free disk space. If not, stop and tell me.
2. Check Docker Engine and "docker compose version" work without sudo. If Docker is
   missing, install it with the official script (get.docker.com) and add me to the
   docker group. Then tell me to log out and log back in, and wait for me.
3. Clone the repo and cd into it.
4. Run ./scripts/docker.sh setup
5. Run ./scripts/docker.sh models and then ./scripts/docker.sh models --kind embeddings.
   These are slow. Do not interrupt or re-run them while they are working.
6. Run docker compose up -d --build --wait, then check docker compose ps shows all
   services healthy. If something fails, read docker compose logs --tail=100 and fix it.
7. Trust the HTTPS certificate at
   .secrets/caddy-data/caddy/pki/authorities/local/root.crt in the system store.
8. Confirm https://localhost:8443 responds, and tell me to open it and create my password.

Rules:
- Never run ./scripts/docker.sh with sudo.
- Ask me before every sudo command.
- Never delete or overwrite .env, .secrets or .local. They hold my data and keys.
- Never disable TLS/certificate checks to make something work.
- Do not change GATEWAY_BIND or open the app to my network unless I ask.
  Keep the app password on.
- At the end, give me a short summary: what you did, the app address, and anything
  that failed.
````

The agent will ask before using `sudo`. Read each command before you say yes.

---

## Easy install

Open a terminal and paste these one at a time.

```sh
# 1. Install Docker (skip if you already have it)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Now log out and log back in, so Docker works without sudo.

# 2. Get the code
git clone https://github.com/Mayank13Jindal/Expo-Buddy.git
cd Expo-Buddy

# 3. Create settings and secrets
./scripts/docker.sh setup

# 4. Download the AI models (this can take a while, don't stop it)
./scripts/docker.sh models
./scripts/docker.sh models --kind embeddings

# 5. Start the app
docker compose up -d --build --wait

# 6. Trust the app's HTTPS certificate (one time only)
sudo install -m 644 .secrets/caddy-data/caddy/pki/authorities/local/root.crt /usr/local/share/ca-certificates/expo-buddy.crt
sudo update-ca-certificates
```

Open **https://localhost:8443** in your browser. Done.

If the browser still warns about the certificate, restart the browser. Chrome on Linux
may need `./scripts/trust-local-ca.sh` as well.

---

## Manual install

### 1. Check your computer

```sh
uname -m          # should print x86_64
df -h .           # need about 15 GB free
```

### 2. Install Docker

Follow Docker's official guide for your Linux version, or use the quick script:

```sh
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

Log out and back in. Check that it works **without** sudo:

```sh
docker run --rm hello-world
docker compose version     # must be v2
```

### 3. Get the code

```sh
git clone https://github.com/Mayank13Jindal/Expo-Buddy.git
cd Expo-Buddy
```

### 4. Run setup

```sh
./scripts/docker.sh setup
```

This creates:

| What | Where | Notes |
|---|---|---|
| Settings | `.env` | You can edit it later |
| Secret keys | `.secrets/` | **Never delete or share** |
| Your data | `.local/data/` | Photos, database, backups |

Running setup again is safe: it does not overwrite an existing `.env`.

### 5. Download the models

```sh
./scripts/docker.sh models                     # text reading (OCR)
./scripts/docker.sh models --kind embeddings   # smart search (optional)
```

You can skip this and start the app first, but card scanning won't work until the models are in place.

### 6. Start the app

```sh
docker compose up -d --build --wait
docker compose ps        # every service should say "healthy"
```

The first build takes several minutes.

### 7. Trust the HTTPS certificate

The app makes its own private certificate. Tell your computer to trust it:

```sh
sudo install -m 644 .secrets/caddy-data/caddy/pki/authorities/local/root.crt /usr/local/share/ca-certificates/expo-buddy.crt
sudo update-ca-certificates
./scripts/trust-local-ca.sh     # for Chrome/Chromium on Linux (needs certutil)
```

Only share `root.crt`. Never share the private key next to it.

### 8. Open it

Go to **https://localhost:8443**.

### 9. Password access

The first time you open the app, it asks you to create a password. To turn the
password off, change `PASSWORDLESS=false` to `PASSWORDLESS=true` in `.env` and run
`docker compose up -d --wait`. Only do that on a computer nobody else can reach.

### 10. Optional: use it on your phone

See [docs/tailscale.md](docs/tailscale.md) for phone access and [docs/pwa.md](docs/pwa.md)
to install it as an app. Keep password access enabled (step 9).

---

## Everyday commands

```sh
docker compose ps                 # is it running?
docker compose logs --tail=100    # see errors
docker compose stop               # stop (your data is kept)
docker compose up -d --wait       # start again
```

## Common problems

| Problem | Fix |
|---|---|
| `permission denied` with Docker | Log out and back in after `usermod`, or run `newgrp docker` |
| `Run this as your normal user` | Don't use `sudo` with `./scripts/docker.sh` |
| Browser says "not secure" | Do step 7, then fully restart the browser |
| Port 8443 already in use | Find the program using it with `sudo ss -ltnp \| grep 8443` and stop it |
| Scanning says models are missing | Run step 5 |
| A service is not healthy | Run `docker compose logs --tail=100` and look for the first error |

Need more detail? See [docs/setup.md](docs/setup.md).