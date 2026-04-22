from __future__ import annotations

import json
import time

from govpress_mcp.common import ToolResponse, ensure_response_size, make_meta
from govpress_mcp.db.qdrant import QdrantHTTPClient
from govpress_mcp.db.redis_cache import TTLCache
from govpress_mcp.db.sqlite import SQLiteStore
from govpress_mcp.tools.search import semantic_items

_TRACE_CACHE: TTLCache[dict] = TTLCache(ttl_seconds=3600)


def trace_policy(
    *,
    store: SQLiteStore,
    qdrant: QdrantHTTPClient,
    tei_url: str,
    keyword: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> ToolResponse:
    started_at = time.perf_counter()
    cache_key = json.dumps(
        {
            "keyword": keyword,
            "date_from": date_from,
            "date_to": date_to,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    cached = _TRACE_CACHE.get(cache_key)
    if cached is not None:
        return ensure_response_size(
            ToolResponse(data=cached, meta=make_meta(started_at, record_count=len(cached["nodes"]), cache_hit=True))
        )

    items = semantic_items(
        store=store,
        qdrant=qdrant,
        tei_url=tei_url,
        query=keyword,
        date_from=date_from,
        date_to=date_to,
        limit=50,
    )
    nodes = sorted(
        [
            {
                "news_item_id": item["news_item_id"],
                "title": item["title"],
                "department": item["department"],
                "approve_date": item["approve_date"],
                "source_url": item["source_url"],
                "score": item["score"],
            }
            for item in items
        ],
        key=lambda item: (item["approve_date"] or "", item["news_item_id"]),
    )[:50]
    data = {"keyword": keyword, "nodes": nodes}
    _TRACE_CACHE.set(cache_key, data)
    return ensure_response_size(
        ToolResponse(data=data, meta=make_meta(started_at, record_count=len(nodes), cache_hit=False))
    )
