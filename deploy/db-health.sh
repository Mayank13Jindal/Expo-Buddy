#!/bin/sh
set -eu
test -f /var/lib/postgresql/.expo-buddy-volume
test ! -L /var/lib/postgresql/.expo-buddy-volume
test "$(cat /var/lib/postgresql/.expo-buddy-volume)" = "$DB_VOLUME_ID"
exec pg_isready -U expo -d "$POSTGRES_DB"

