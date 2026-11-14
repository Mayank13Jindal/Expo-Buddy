#!/bin/sh
set -eu
marker=/var/lib/postgresql/.expo-buddy-volume
if [ ! -f "$marker" ] || [ -L "$marker" ] || [ "$(cat "$marker")" != "$DB_VOLUME_ID" ]; then
  echo 'Storage drive not found: database' >&2
  exit 1
fi
exec /usr/local/bin/docker-entrypoint.sh "$@"

