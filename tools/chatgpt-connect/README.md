# ChatGPT PC sign-in helper

Download the server-bound helper from Expo Buddy → AI & ChatGPT → Continue with ChatGPT. It bundles `connect_helper.py`, `oauth_crypto.py`, pinned requirements and the server's **public** host profile. Run it on the computer opening the browser, then import its protected `.expo` output through the app.

The source is in `backend/app/providers/connect_helper.py` and `oauth_crypto.py`; the authenticated download endpoint assembles the ZIP. It performs the documented OAuth public-client flow, not token scraping or Codex credential copying. See [the full connection guide](../../docs/chatgpt-connection.md). Never share credentials in chat or commit a connection file.
