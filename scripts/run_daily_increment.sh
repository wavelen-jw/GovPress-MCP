#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DATE="$(TZ=Asia/Seoul date --date='yesterday' +%F)"
TARGET_STAMP="${TARGET_DATE//-/}"
LOG_PATH="data/fetch-log/daily-${TARGET_STAMP}.jsonl"

cd "$ROOT_DIR"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  source "$ROOT_DIR/.env"
  set +a
fi

export TZ=Asia/Seoul
export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

exec "$ROOT_DIR/.venv/bin/python" -m govpress_mcp.bulk_ingest \
  --date "$TARGET_DATE" \
  --data-root "$ROOT_DIR/data" \
  --log-json "$LOG_PATH"
