# Install Expo Buddy

For the shorter options, see [AI-assisted install](README.md#ai-assisted-install)
and [Easy install](README.md#easy-install) on the project home page.

**You need:** a Linux x86-64 computer (Ubuntu or Debian is easiest), about 15 GB free
disk space, Git, curl and an internet connection. Builds and downloads can take longer
on slower computers or connections. Windows and macOS are not supported yet.

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
sudo usermod -aG docker "$USER"
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
sudo apt install -y libnss3-tools
./scripts/trust-local-ca.sh     # for Chrome/Chromium on Linux
```

Firefox keeps its own list. Open **Settings > Privacy & Security > Certificates >
View Certificates > Authorities > Import**, pick `root.crt`, and tick
**Trust this CA to identify websites**.

Only share `root.crt`. Never share the private key next to it.

### 8. Open it

Go to **https://localhost:8443**.

### 9. Password access

The first time you open the app, it asks you to create a password. To turn the
password off, change `PASSWORDLESS=false` to `PASSWORDLESS=true` in `.env` and run
`docker compose up -d --wait`. Only do that on a computer nobody else can reach.

If you forget your password, run:

```sh
docker compose exec api python -m app.core.reset_password
```

This only works after the account exists (after first sign-in).

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
| Port 8443, 8080 or 1455 already in use | Find the program with `sudo ss -ltnp \| grep -E ':(8443\|8080\|1455)\b'` and stop it |
| Scanning says models are missing | Run step 5 |
| A service is not healthy | Run `docker compose logs --tail=100` and look for the first error |
| Chrome says "not secure" | `sudo apt install -y libnss3-tools`, then `./scripts/trust-local-ca.sh`, then restart Chrome |
| Forgot the app password | `docker compose exec api python -m app.core.reset_password` |
| "No account yet" when resetting the password | Open the app once and create the account first |

Need more detail? See [docs/setup.md](docs/setup.md).
