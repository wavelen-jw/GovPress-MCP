from __future__ import annotations

import json
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


_WRITE_LOCK = threading.Lock()
_KST = timezone(timedelta(hours=9))


def _now_iso() -> str:
    return datetime.now(_KST).isoformat(timespec="seconds")


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return value[:200]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _sanitize_value(v) for k, v in list(value.items())[:20]}
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(v) for v in list(value)[:20]]
    return str(value)


class UsageLogger:
    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_tool_call(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        response: dict[str, Any] | None,
        latency_ms: float,
        response_bytes: int,
        exception: Exception | None = None,
    ) -> None:
        meta = response.get("meta", {}) if isinstance(response, dict) else {}
        error = None
        if isinstance(response, dict):
            error = response.get("error")

        event = {
            "timestamp": _now_iso(),
            "tool_name": tool_name,
            "arguments": _sanitize_value(arguments),
            "latency_ms": round(latency_ms, 2),
            "response_bytes": response_bytes,
            "record_count": int(meta.get("record_count", 0) or 0),
            "cache_hit": bool(meta.get("cache_hit", False)),
            "status": "exception" if exception else ("error" if error else "ok"),
            "error": str(exception) if exception else error,
        }

        line = json.dumps(event, ensure_ascii=False) + "\n"
        with _WRITE_LOCK:
            with self.log_path.open("a", encoding="utf-8") as fp:
                fp.write(line)


def summarize_usage(log_path: Path, *, recent_limit: int = 50) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    if log_path.exists():
        with log_path.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    now = datetime.now(_KST)
    since_24h = now - timedelta(hours=24)

    tool_counter = Counter()
    status_counter = Counter()
    tool_counter_24h = Counter()
    status_counter_24h = Counter()
    latencies: list[float] = []
    latencies_24h: list[float] = []

    recent = rows[-recent_limit:]

    for row in rows:
        tool = str(row.get("tool_name", "unknown"))
        status = str(row.get("status", "unknown"))
        tool_counter[tool] += 1
        status_counter[status] += 1

        latency = row.get("latency_ms")
        if isinstance(latency, (int, float)):
            latencies.append(float(latency))

        timestamp = row.get("timestamp")
        ts = None
        if isinstance(timestamp, str):
            try:
                ts = datetime.fromisoformat(timestamp)
            except ValueError:
                ts = None
        if ts is not None and ts >= since_24h:
            tool_counter_24h[tool] += 1
            status_counter_24h[status] += 1
            if isinstance(latency, (int, float)):
                latencies_24h.append(float(latency))

    def _avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 2) if values else 0.0

    return {
        "log_path": str(log_path),
        "total_requests": len(rows),
        "requests_24h": sum(tool_counter_24h.values()),
        "by_tool": dict(tool_counter.most_common()),
        "by_tool_24h": dict(tool_counter_24h.most_common()),
        "by_status": dict(status_counter.most_common()),
        "by_status_24h": dict(status_counter_24h.most_common()),
        "avg_latency_ms": _avg(latencies),
        "avg_latency_ms_24h": _avg(latencies_24h),
        "recent": recent,
        "generated_at": _now_iso(),
    }


def render_usage_dashboard(summary: dict[str, Any]) -> str:
    by_tool_rows = "".join(
        f"<tr><td>{tool}</td><td>{count}</td><td>{summary['by_tool_24h'].get(tool, 0)}</td></tr>"
        for tool, count in summary["by_tool"].items()
    )
    recent_rows = "".join(
        "<tr>"
        f"<td>{row.get('timestamp','')}</td>"
        f"<td>{row.get('tool_name','')}</td>"
        f"<td>{row.get('status','')}</td>"
        f"<td>{row.get('latency_ms','')}</td>"
        f"<td>{row.get('record_count','')}</td>"
        f"<td>{'Y' if row.get('cache_hit') else ''}</td>"
        f"<td><code>{json.dumps(row.get('arguments', {}), ensure_ascii=False)}</code></td>"
        "</tr>"
        for row in reversed(summary["recent"])
    )
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Govpress MCP Usage Dashboard</title>
  <style>
    body {{ font-family: sans-serif; margin: 24px; color: #111; }}
    h1, h2 {{ margin: 0 0 12px; }}
    .stats {{ display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)); gap: 12px; margin: 16px 0 24px; }}
    .card {{ border: 1px solid #ddd; border-radius: 8px; padding: 12px; background: #fafafa; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f3f3f3; }}
    code {{ white-space: pre-wrap; word-break: break-word; }}
    .muted {{ color: #666; }}
  </style>
</head>
<body>
  <h1>Govpress MCP Usage Dashboard</h1>
  <p class="muted">generated_at={summary['generated_at']} · log={summary['log_path']}</p>
  <div class="stats">
    <div class="card"><strong>총 요청</strong><br>{summary['total_requests']}</div>
    <div class="card"><strong>최근 24시간</strong><br>{summary['requests_24h']}</div>
    <div class="card"><strong>평균 지연</strong><br>{summary['avg_latency_ms']} ms</div>
    <div class="card"><strong>24시간 평균 지연</strong><br>{summary['avg_latency_ms_24h']} ms</div>
  </div>

  <h2>도구별 사용량</h2>
  <table>
    <thead><tr><th>도구</th><th>전체</th><th>최근 24시간</th></tr></thead>
    <tbody>{by_tool_rows}</tbody>
  </table>

  <h2>최근 요청</h2>
  <table>
    <thead><tr><th>시각</th><th>도구</th><th>상태</th><th>지연(ms)</th><th>record_count</th><th>cache</th><th>arguments</th></tr></thead>
    <tbody>{recent_rows}</tbody>
  </table>
</body>
</html>"""
