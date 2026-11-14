# Connect your ChatGPT plan

The official [Sign in with ChatGPT guide for open-source apps](https://developers.openai.com/siwc/token-sharing-open-source/sign-in) and [self-hosted VM guide](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms) now document the required flow. This supersedes the earlier release's unavailable placeholder. Expo Buddy implements dynamic client registration, a PC loopback callback, protected transfer, account-specific model discovery, renewable credentials and Responses streaming. Actual sign-in/eligibility/inference still require the owner's account and consent; automated fake-credential tests do not prove that an account has access.

On the computer running Expo Buddy, open **Settings → AI connections & models → Sign in on server PC**. OpenAI opens in another tab and returns to a `127.0.0.1` callback; the app saves the verified connection automatically. Docker publishes this callback only on host loopback port 1455 (`CHATGPT_CALLBACK_PORT` can change it). A native API process binds loopback by default. Keep the callback off public/LAN interfaces.

The account badge reports **Connected** or **Signed out** independently from the card-processing toggle and cloud permission. Use **Sign out of ChatGPT** for a connected account; a fresh successful sign-in re-enables the provider. The model choice is retained, and cloud permission is preserved.

On a different computer, choose **Connect from another PC**. Download the helper ZIP on the PC where you will open the browser, extract it and follow README.txt. With Python 3.12 installed:

```sh
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
python connect_helper.py
# If the browser does not open, copy the link printed by the helper.
# Run --no-browser when you want to open that link yourself on this same PC.
```

Sign in only on OpenAI's page. Grant ChatGPT plan usage if you want extraction. The helper listens only on `127.0.0.1` with a random available port and `/auth/callback`, starts that listener before opening the browser, and verifies state, PKCE, nonce, signed ID-token issuer/audience/expiry and the issued client ID. A declined or expired flow stops. Passwords are never entered into Expo Buddy or the helper.

Import the generated `chatgpt-connection.expo` through the connection dialog. It is encrypted for this server's public transfer key, derived from the existing protected encryption key and host identity. The server verifies identity again, preserves its own host ID and encrypts credentials at rest. Replaying an already-imported file is refused so it cannot roll a rotated refresh token backward. Delete the transfer file after import. Keep `.secrets/encryption_key` and `.secrets/host_id` private and persistent.

Then load the account's available models, select an exact model ID, enable **Use my ChatGPT plan** and cloud processing, and save. The selected ID remains saved; choose a versioned model ID when the catalog offers one. A rolling model alias is not a cryptographic weight pin. **Test saved connection** performs a fictional extraction. “Connected” means imported/validated credentials; only an actual successful extraction changes the provider status to online.

Existing account registrations keep their issued client ID on reauthorization. Use **Use a different ChatGPT account** to create a distinct registration; the account picker distinguishes registrations by label and ID. Up to five registrations are retained. Disconnect attempts remote revocation and clears the selected account's local tokens. If revocation cannot be confirmed, the app says so; disconnect it in ChatGPT Settings too. The official VM-transfer guide warns that transferred sessions do not currently have independent host-specific attribution/revocation.

Inference uses the documented public `https://api.openai.com/v1/responses` endpoint with `store=false`, `stream=true`, the pinned selected model, structured output and no tools. It does not call ChatGPT backend-api endpoints or run Codex/shell agents. A stream succeeds only after `response.completed`; a late error, incomplete or disconnected stream never produces accepted fields. Expiring credentials are refreshed under a DB row lock, rotating the saved refresh token atomically. Missing plan scope or permission errors stop processing; temporary outages/limits may use the owner's explicitly enabled fallback. Model discovery uses the selected account's current catalog, not an invented list.

Provider credentials are excluded from backups. Restoration requires reconnection. Existing personal notes are not sent. The optional note entered at capture or reprocessing is explicitly AI context; image checks are a separate local-Ollama-only action.

Official references checked on 29 October 2026: [registration/sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in), [accounts/refresh/revocation](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions), [models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference), [current request restrictions](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations), [self-hosted transfer](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms). Eligible account/workspace policy and usage limits apply; the app reports their failures and does not claim access in advance.
