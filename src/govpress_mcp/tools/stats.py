from __future__ import annotations

import time

from govpress_mcp.common import ToolResponse, ensure_response_size, make_meta
from govpress_mcp.db.qdrant import QdrantHTTPClient
from govpress_mcp.db.sqlite import SQLiteStore


def get_stats(*, store: SQLiteStore, qdrant: QdrantHTTPClient) -> ToolResponse:
    started_at = time.perf_counter()
    stats = store.stats()
    qdrant_stats = qdrant.collection_stats()
    payload = {
        **stats,
        "qdrant_points_count": qdrant_stats.points_count,
        "qdrant_indexed_vectors_count": qdrant_stats.indexed_vectors_count,
        "qdrant_status": qdrant_stats.status,
    }
    response = ToolResponse(
        data=payload,
        meta=make_meta(started_at, record_count=1, cache_hit=False),
    )
    return ensure_response_size(response)
