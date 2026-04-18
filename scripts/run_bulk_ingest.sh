#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  source "$ROOT_DIR/.env"
  set +a
fi

export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$ROOT_DIR/.venv/bin/python" -m govpress_mcp.bulk_ingest "$@"
