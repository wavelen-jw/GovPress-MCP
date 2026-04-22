from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from govpress_mcp.usage import UsageLogger, render_usage_dashboard, summarize_usage


def test_usage_logger_and_summary() -> None:
    with TemporaryDirectory() as tmp_dir:
        log_path = Path(tmp_dir) / "mcp-usage.jsonl"
        logger = UsageLogger(log_path)

        logger.log_tool_call(
            tool_name="get_stats",
            arguments={},
            response={"data": {"ok": True}, "error": None, "meta": {"record_count": 1, "cache_hit": False}},
            latency_ms=12.34,
            response_bytes=128,
        )
        logger.log_tool_call(
            tool_name="trace_policy",
            arguments={"keyword": "디지털플랫폼정부"},
            response={"data": None, "error": "response_too_large", "meta": {"record_count": 0, "cache_hit": False}},
            latency_ms=55.0,
            response_bytes=256,
        )

        summary = summarize_usage(log_path)

        assert summary["total_requests"] == 2
        assert summary["by_tool"]["get_stats"] == 1
        assert summary["by_tool"]["trace_policy"] == 1
        assert summary["by_status"]["ok"] == 1
        assert summary["by_status"]["error"] == 1
        assert len(summary["recent"]) == 2


def test_usage_dashboard_render() -> None:
    summary = {
        "log_path": "/tmp/mcp-usage.jsonl",
        "total_requests": 2,
        "requests_24h": 2,
        "by_tool": {"get_stats": 1, "trace_policy": 1},
        "by_tool_24h": {"get_stats": 1, "trace_policy": 1},
        "by_status": {"ok": 1, "error": 1},
        "by_status_24h": {"ok": 1, "error": 1},
        "avg_latency_ms": 33.67,
        "avg_latency_ms_24h": 33.67,
        "recent": [
            {
                "timestamp": "2026-04-22T18:00:00+09:00",
                "tool_name": "get_stats",
                "status": "ok",
                "latency_ms": 12.34,
                "record_count": 1,
                "cache_hit": False,
                "arguments": {},
            }
        ],
        "generated_at": "2026-04-22T18:00:05+09:00",
    }

    html = render_usage_dashboard(summary)

    assert "Govpress MCP Usage Dashboard" in html
    assert "get_stats" in html
    assert "2026-04-22T18:00:00+09:00" in html
