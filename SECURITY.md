# Security

Expo Buddy is a single-owner application for a trusted host/LAN/VPN. Its default
local setup asks you to create a password on first use and binds to loopback.
Optional password-free mode gives anyone who can reach the app full access; never
use it on a network you do not fully trust. AI providers and agents receive only the access you
enable, but data read by a separately configured cloud agent may leave your network.

For a vulnerability, use the repository's **Security → Report a vulnerability**
private advisory flow if enabled. Otherwise contact the maintainer privately before
posting details. Never include provider tokens, cookies, passwords, encryption
keys, database dumps, real cards or private notes in a public issue.

Updates are currently maintained on the main branch; there is no promised support
window for old releases. Back up before upgrades and verify restore on your own
hardware. The project has automated checks but has not had an independent security
audit. Dependency licenses/notices are in `docs/NOTICES.md`.
