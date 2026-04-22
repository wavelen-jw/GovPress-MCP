from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_ROOT = REPO_ROOT / "data"
DEFAULT_DB_PATH = DEFAULT_DATA_ROOT / "govpress.db"
DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_TEI_URL = "http://localhost:18080"
DEFAULT_MCP_PORT = 8000
DEFAULT_USAGE_LOG_PATH = DEFAULT_DATA_ROOT / "fetch-log" / "mcp-usage.jsonl"
RESPONSE_SIZE_LIMIT = 50 * 1024


@dataclass
class ToolResponse:
    data: dict | list | None
    error: str | None = None
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class Settings:
    data_root: Path = DEFAULT_DATA_ROOT
    db_path: Path = DEFAULT_DB_PATH
    qdrant_url: str = DEFAULT_QDRANT_URL
    tei_url: str = DEFAULT_TEI_URL
    mcp_port: int = DEFAULT_MCP_PORT
    usage_log_path: Path = DEFAULT_USAGE_LOG_PATH


def load_settings() -> Settings:
    data_root = Path(os.environ.get("DATA_ROOT", str(DEFAULT_DATA_ROOT))).expanduser().resolve()
    db_path = Path(os.environ.get("DB_PATH", str(DEFAULT_DB_PATH))).expanduser().resolve()
    qdrant_url = os.environ.get("QDRANT_URL", DEFAULT_QDRANT_URL)
    tei_url = os.environ.get("TEI_URL", DEFAULT_TEI_URL)
    mcp_port = int(os.environ.get("MCP_PORT", str(DEFAULT_MCP_PORT)))
    usage_log_path = Path(os.environ.get("USAGE_LOG_PATH", str(DEFAULT_USAGE_LOG_PATH))).expanduser().resolve()
    return Settings(
        data_root=data_root,
        db_path=db_path,
        qdrant_url=qdrant_url,
        tei_url=tei_url,
        mcp_port=mcp_port,
        usage_log_path=usage_log_path,
    )


def make_meta(started_at: float, *, record_count: int, cache_hit: bool = False, **extra: object) -> dict[str, object]:
    meta: dict[str, object] = {
        "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
        "record_count": record_count,
        "cache_hit": cache_hit,
    }
    meta.update(extra)
    return meta


def ensure_response_size(response: ToolResponse) -> ToolResponse:
    payload = json.dumps(response.to_dict(), ensure_ascii=False).encode("utf-8")
    if len(payload) <= RESPONSE_SIZE_LIMIT:
        return response
    return ToolResponse(
        data=None,
        error=f"response_too_large:{len(payload)}",
        meta=response.meta,
    )


def smart_truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    candidate = text[:max_chars]
    boundary = max(candidate.rfind("\n## "), candidate.rfind("\n### "))
    if boundary > max_chars // 2:
        candidate = candidate[:boundary]
    marker = f"\n\n[...이하 생략 (총 {len(text)}자 중 {len(candidate)}자)...]\n"
    return candidate.rstrip() + marker
