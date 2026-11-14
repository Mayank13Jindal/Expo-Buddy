#!/bin/sh
# Trust only this disposable stack's public CA in this user's browser profile.
set -eu
project_dir=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
certificate="$project_dir/.secrets/caddy-data/caddy/pki/authorities/local/root.crt"
test -f "$certificate"
command -v certutil >/dev/null
mkdir -p "$HOME/.pki/nssdb"
if [ ! -f "$HOME/.pki/nssdb/cert9.db" ]; then
  certutil -N -d "sql:$HOME/.pki/nssdb" --empty-password
fi
certutil -A -d "sql:$HOME/.pki/nssdb" -n 'Expo Buddy local development CA' -t 'C,,' -i "$certificate"
echo 'Trusted the local development CA for this user. HTTPS verification remains enabled.'
