from __future__ import annotations

import json
import time
from urllib.request import Request, urlopen

from govpress_mcp.common import ToolResponse, ensure_response_size, make_meta
from govpress_mcp.db.qdrant import QdrantHTTPClient
from govpress_mcp.db.redis_cache import TTLCache
from govpress_mcp.db.sqlite import SQLiteStore

_FTS_CACHE: TTLCache[dict] = TTLCache(ttl_seconds=3600)
_SEMANTIC_CACHE: TTLCache[dict] = TTLCache(ttl_seconds=3600)


def fts_search(
    *,
    store: SQLiteStore,
    query: str,
    limit: int = 10,
) -> ToolResponse:
    started_at = time.perf_counter()
    cache_key = json.dumps({"query": query, "limit": limit}, ensure_ascii=False, sort_keys=True)
    cached = _FTS_CACHE.get(cache_key)
    if cached is not None:
        response = ToolResponse(data=cached, meta=make_meta(started_at, record_count=len(cached["items"]), cache_hit=True))
        return ensure_response_size(response)

    rows = store.fts_search(query, limit=min(max(limit, 1), 50))
    items = []
    for row in rows:
        items.append(
            {
                "news_item_id": row["news_item_id"],
                "title": row["title"],
                "department": row["department"],
                "approve_date": row["approve_date"],
                "source_url": row["source_url"],
                "source_format": row["source_format"],
                "chunk_index": row["chunk_index"],
                "snippet": row["snippet"],
                "score": round(1 / (1 + max(float(row["rank"]), 0.0)), 6),
            }
        )
    data = {"query": query, "items": items}
    _FTS_CACHE.set(cache_key, data)
    response = ToolResponse(data=data, meta=make_meta(started_at, record_count=len(items), cache_hit=False))
    return ensure_response_size(response)


def search_briefing(
    *,
    store: SQLiteStore,
    qdrant: QdrantHTTPClient,
    tei_url: str,
    query: str,
    date_from: str | None = None,
    date_to: str | None = None,
    ministry: str | None = None,
    limit: int = 10,
) -> ToolResponse:
    started_at = time.perf_counter()
    cache_key = json.dumps(
        {
            "query": query,
            "date_from": date_from,
            "date_to": date_to,
            "ministry": ministry,
            "limit": limit,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    cached = _SEMANTIC_CACHE.get(cache_key)
    if cached is not None:
        response = ToolResponse(data=cached, meta=make_meta(started_at, record_count=len(cached["items"]), cache_hit=True))
        return ensure_response_size(response)

    items = semantic_items(
        store=store,
        qdrant=qdrant,
        tei_url=tei_url,
        query=query,
        date_from=date_from,
        date_to=date_to,
        ministry=ministry,
        limit=limit,
    )
    data = {"query": query, "items": items}
    _SEMANTIC_CACHE.set(cache_key, data)
    response = ToolResponse(data=data, meta=make_meta(started_at, record_count=len(items), cache_hit=False))
    return ensure_response_size(response)


def semantic_items(
    *,
    store: SQLiteStore,
    qdrant: QdrantHTTPClient,
    tei_url: str,
    query: str,
    date_from: str | None = None,
    date_to: str | None = None,
    ministry: str | None = None,
    limit: int = 10,
) -> list[dict]:
    vector = _embed_query(tei_url, query)
    hits = qdrant.search(vector, limit=min(max(limit, 1), 50) * 5, score_threshold=0.5)
    chunk_bodies = store.get_chunk_bodies([hit.chunk_id for hit in hits if hit.chunk_id])
    meta_map = store.get_doc_meta_map([hit.news_item_id for hit in hits if hit.news_item_id])

    deduped: dict[str, dict] = {}
    for hit in hits:
        meta = meta_map.get(hit.news_item_id)
        if meta is None:
            continue
        if date_from and meta.get("approve_date") and str(meta["approve_date"]) < date_from:
            continue
        if date_to and meta.get("approve_date") and str(meta["approve_date"]) > date_to:
            continue
        if ministry and meta.get("department") != ministry:
            continue
        current = deduped.get(hit.news_item_id)
        if current is not None and current["score"] >= hit.score:
            continue
        deduped[hit.news_item_id] = {
            "news_item_id": hit.news_item_id,
            "title": meta["title"],
            "department": meta["department"],
            "approve_date": meta["approve_date"],
            "source_url": meta["source_url"],
            "source_format": meta["source_format"],
            "score": round(hit.score, 6),
            "chunk_id": hit.chunk_id,
            "snippet": _preview(chunk_bodies.get(hit.chunk_id, "")),
        }
    return sorted(deduped.values(), key=lambda item: item["score"], reverse=True)[: min(max(limit, 1), 50)]


def _embed_query(tei_url: str, query: str) -> list[float]:
    req = Request(
        tei_url.rstrip("/") + "/embed",
        data=json.dumps({"inputs": [query]}).encode("utf-8"),
        headers={"content-type": "application/json"},
    )
    with urlopen(req, timeout=30) as response:
        payload = json.load(response)
    return [float(value) for value in payload[0]]


def _preview(text: str, max_chars: int = 240) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars].rstrip() + "..."
