#!/bin/sh
# Run host-side Python utilities without installing Python on the host.
set -eu
project_dir=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
case "${1:-}" in
  setup) shift; script=setup.py; set -- --local "$@" ;;
  models) shift; script=download_models.py ;;
  *) echo 'Usage: ./scripts/docker.sh setup [setup options] | models [--kind ocr|embeddings]' >&2; exit 2 ;;
esac
if [ "$(id -u)" = 0 ]; then
  echo 'Run this as your normal user with access to Docker, not with sudo.' >&2
  exit 1
fi
command -v docker >/dev/null
docker compose version >/dev/null
# Keep the terminal interactive so setup can ask questions.
tty_flags=''
if [ -t 0 ] && [ -t 1 ]; then tty_flags='-it'; fi
# shellcheck disable=SC2086
exec docker run --rm $tty_flags --user "$(id -u):$(id -g)" \
  --env PYTHONDONTWRITEBYTECODE=1 \
  --mount "type=bind,source=$project_dir,target=$project_dir" \
  --workdir "$project_dir" \
  python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e \
  python "scripts/$script" "$@"
