#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "[1/5] tracked secret patterns"
if git grep -nE '(GOVPRESS_POLICY_BRIEFING_SERVICE_KEY=|cfut_|CLOUDFLARE_TUNNEL_TOKEN=|BEGIN PRIVATE KEY)' -- . ':!LICENSE-data' ':!.env.example'; then
  echo "secret-like pattern found"
  exit 1
fi

echo "[2/5] forbidden tracked paths"
for path in .env data logs; do
  if git ls-files --error-unmatch "$path" >/dev/null 2>&1; then
    echo "tracked forbidden path: $path"
    exit 1
  fi
done

echo "[3/5] required public docs"
for path in README.md LICENSE LICENSE-data docs/phase1-report.md docs/phase2-report.md docs/derive-hot-report.md docs/t4-cloudflare-report.md; do
  test -f "$path" || { echo "missing required file: $path"; exit 1; }
done

echo "[4/5] compare_versions hidden from tools/list"
python3 - <<'PY'
import json, urllib.request
req = urllib.request.Request(
    'http://127.0.0.1:8001/mcp',
    data=json.dumps({"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}).encode(),
    headers={'Accept':'application/json, text/event-stream','Content-Type':'application/json'},
    method='POST',
)
with urllib.request.urlopen(req, timeout=30) as resp:
    obj = json.load(resp)
names = {tool["name"] for tool in obj["result"]["tools"]}
assert "compare_versions" not in names, names
print("public tools:", sorted(names))
PY

echo "[5/5] public endpoint reachable"
curl -fsS https://mcp.govpress.cloud/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' >/dev/null

echo "prepublish check passed"
