from __future__ import annotations

import json
import time

from govpress_mcp.common import ToolResponse, ensure_response_size, make_meta
from govpress_mcp.db.qdrant import QdrantHTTPClient
from govpress_mcp.db.redis_cache import TTLCache
from govpress_mcp.db.sqlite import SQLiteStore
from govpress_mcp.tools.search import semantic_items

_CROSS_CACHE: TTLCache[dict] = TTLCache(ttl_seconds=3600)


def cross_check_ministries(
    *,
    store: SQLiteStore,
    qdrant: QdrantHTTPClient,
    tei_url: str,
    topic: str,
    date_from: str | None = None,
    date_to: str | None = None,
    min_ministries: int = 2,
) -> ToolResponse:
    started_at = time.perf_counter()
    cache_key = json.dumps(
        {
            "topic": topic,
            "date_from": date_from,
            "date_to": date_to,
            "min_ministries": min_ministries,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    cached = _CROSS_CACHE.get(cache_key)
    if cached is not None:
        return ensure_response_size(
            ToolResponse(data=cached, meta=make_meta(started_at, record_count=len(cached["items"]), cache_hit=True))
        )

    items = semantic_items(
        store=store,
        qdrant=qdrant,
        tei_url=tei_url,
        query=topic,
        date_from=date_from,
        date_to=date_to,
        limit=50,
    )
    grouped: dict[str, dict] = {}
    for item in items:
        department = item.get("department") or "unknown"
        current = grouped.get(department)
        if current is None or current["score"] < item["score"]:
            grouped[department] = item
    ministry_items = sorted(grouped.values(), key=lambda item: item["score"], reverse=True)[:5]

    data = {
        "topic": topic,
        "min_ministries": min_ministries,
        "items": ministry_items,
        "enough_ministries": len(ministry_items) >= min_ministries,
    }
    _CROSS_CACHE.set(cache_key, data)
    return ensure_response_size(
        ToolResponse(data=data, meta=make_meta(started_at, record_count=len(ministry_items), cache_hit=False))
    )
