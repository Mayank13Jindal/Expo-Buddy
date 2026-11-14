#!/bin/sh
set -eu
exec /opt/pg-tools/lib/ld-linux-x86-64.so.2 --library-path /opt/pg-tools/lib /opt/pg-tools/pg_dump "$@"
