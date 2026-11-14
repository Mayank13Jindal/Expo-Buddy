# One trusted HTTPS address

HTTPS encrypts passwords and contact records. Browsers also require a trusted secure origin for service workers, which provide this app's offline capture and installation. An ordinary HTTP page can display a library, but it cannot provide the same reliable phone/offline behavior. HTTPS does not require a public website or public access to your records.

Choose `APP_URL` once and install the PWA only from that address. Browser queues belong to an origin: a LAN IP, a Tailscale name and an owner domain are separate origins. Keep the same address at home and away; the phone may need Tailscale enabled at home too. VPN installation itself is outside this app.

## Automatic setup on the existing server

Keep the working LAN address while applying code updates. Port **443** is the standard external HTTPS port; container port 8443 is an internal implementation detail and does not require phones to open 8443.

Run `python3 scripts/doctor_network.py` on the server to distinguish an unreachable port, a certificate trust/hostname error and an unhealthy application. It verifies certificates; it never disables TLS checks or prints credentials. `--url https://YOUR-HOST` checks another address. A successful check on the server still needs a phone connection test.

To keep the private LAN address on standard port 443, preview:

```sh
python3 scripts/configure_https.py --mode lan --url https://192.168.1.100
```

This retains private-CA trust requirements. A publicly trusted certificate cannot be issued for the private address `192.168.1.100`. To avoid installing a CA on Android, install/sign in to Tailscale on the server and phone, enable MagicDNS and HTTPS in the tailnet, then preview:

```sh
python3 scripts/configure_https.py --mode tailscale
```

The helper discovers the server's full `*.ts.net` name. Add `--apply` to the chosen command to activate it on the server. It writes a private local Compose override, replaces both default port mappings, updates the canonical origin consistently, restarts services without rebuilding images and restores the old configuration if activation fails. Tailscale mode exposes the HTTP backend only on loopback and uses `tailscale serve --bg --https=443` for the trusted HTTPS edge and automatic certificate renewal. Phones must keep Tailscale connected. This uses private Serve, with no public Funnel endpoint.

Preserve any existing Docker overrides. Conventional `docker-compose.override.yml` and the workspace proxy override are included automatically; pass `--compose-file path/to/your-existing-override.yml` for others, particularly Docker-to-host Ollama networking. The generated `deploy/https.local.yml` is used automatically by Make; include it last if running Compose manually. Current stable Docker Compose supports the required `!override` tag. Another service already using Tailscale port 443 is detected and left alone.

Before changing origin, sync every phone's queue at the old address. Local browser captures cannot be moved to a new origin by the server. Sign in again and install/open the app from the new hostname. Keep `.env.before-https` private; it is excluded from source bundles. Verify the chosen address from each device after applying the change.

## Tailscale machine name

Use the server's full MagicDNS name, such as `https://expo-server.YOUR-TAILNET.ts.net`. Enable HTTPS certificates for the tailnet and obtain the certificate on the host with `tailscale cert <full-name>` following [Tailscale's official HTTPS guide](https://tailscale.com/kb/1153/enabling-https). Certificate names appear in public certificate-transparency logs.

Store that certificate and private key in a private folder owned by the configured app UID, mode 0600 for the key. Add a local Compose override mounting the folder read-only in `gateway` at `/run/tls`. Set these `.env` values consistently:

```dotenv
APP_URL=https://expo-server.YOUR-TAILNET.ts.net
APP_HOST=expo-server.YOUR-TAILNET.ts.net
APP_AUTHORITY=expo-server.YOUR-TAILNET.ts.net
GATEWAY_BIND=0.0.0.0
GATEWAY_HTTPS_PORT=443
CADDY_TLS='/run/tls/server.crt /run/tls/server.key'
```

Use your actual filenames. Set host firewall/Tailscale ACLs so access is limited to your devices and Hermes. Renew the host-managed certificate before expiry, replace the mounted files safely, and restart the gateway (`docker compose restart gateway`; its admin endpoint is disabled). Containers do not mount the Tailscale socket or manage your VPN.

## Owner domain

Use one hostname, for example `expo.YOUR-DOMAIN`. Resolve it to the Tailscale IP, or use split DNS (LAN IP at home, Tailscale IP away). Obtain a trusted DNS-01 certificate with the owner's existing certificate manager/proxy, and use the certificate-file method above. The stock Caddy build does not include arbitrary DNS-provider plugins; use your existing trusted certificate manager or explicitly build/pin the appropriate official DNS module. The app does not require public inbound internet access.

## Existing HTTPS proxy or Tailscale Serve

An existing HTTPS proxy can terminate TLS and forward to a loopback-only HTTP gateway. Use `deploy/Caddyfile.proxy` as the gateway configuration instead of the default TLS file; the default port-8080 configuration only redirects and must not be used as the application backend. A local override can include:

```yaml
services:
  gateway:
    ports: !override
      - '127.0.0.1:8080:8080'
    volumes:
      - ./deploy/Caddyfile.proxy:/etc/caddy/Caddyfile:ro
```

Keep `APP_URL`, `APP_HOST` and `APP_AUTHORITY` set to the external HTTPS hostname. Preserve that canonical Host header, request bodies, cookies and SSE streaming; allow at least 404 MiB bodies and 30-minute upload/read timeouts. A wrong Host redirects to `APP_URL`. An upstream that overwrites Host can cause a redirect loop; configure it to forward the canonical host.

Tailscale Serve can provide the private HTTPS edge for a local service; see [the current official Serve guide](https://tailscale.com/kb/1242/tailscale-serve). Use the loopback HTTP configuration above for its backend. Verify the Host header and canonical URL before installing the PWA. Never disable TLS certificate verification in app clients or Hermes.

## Internal Caddy CA

For a private name without an external certificate, use `CADDY_TLS=internal`. Copy only Caddy's **public root certificate** from `.secrets/caddy-data/caddy/pki/authorities/local/root.crt` to each device. Protect the private key and the rest of `.secrets`.

On Android, install the CA using the device's security/certificate settings, then reopen the canonical HTTPS URL in Chrome. OEM menus vary. On iPhone, install the CA profile, then explicitly enable trust under Settings → General → About → Certificate Trust Settings. Remove the profile if you stop trusting this server. A public trusted certificate avoids this device setup.

## Check before installing

1. Open `APP_URL` from the PC and phone without any certificate warning.
2. On the phone, turn Wi-Fi off and keep Tailscale on; open the same URL.
3. Capture a fictional item offline, reconnect and check it arrives under its captured expo.
4. Opening an alternate **HTTP** host/IP redirects to the canonical URL. HTTPS must pass certificate validation before an HTTP redirect is possible; a private IP usually is not covered by a hostname certificate. Use the canonical name directly instead of bypassing a certificate warning.

The gateway enforces the canonical Host, and `/api/v1/health` reports the configured canonical URL. Don't clear an old origin's unsynced queue while changing addresses; sync it first.
