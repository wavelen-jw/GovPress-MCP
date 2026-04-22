from __future__ import annotations

import time

from govpress_mcp.common import ToolResponse, ensure_response_size, make_meta
from govpress_mcp.db.sqlite import SQLiteStore


def list_briefings(
    *,
    store: SQLiteStore,
    date_from: str | None = None,
    date_to: str | None = None,
    department: str | None = None,
    entity_type: str | None = None,
    source_format: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> ToolResponse:
    started_at = time.perf_counter()
    bounded_page_size = max(1, min(page_size, 100))
    total, items = store.list_briefings(
        date_from=date_from,
        date_to=date_to,
        department=department,
        entity_type=entity_type,
        source_format=source_format,
        page=page,
        page_size=bounded_page_size,
    )
    response = ToolResponse(
        data={
            "items": items,
            "page": page,
            "page_size": bounded_page_size,
            "total": total,
            "has_more": page * bounded_page_size < total,
        },
        meta=make_meta(started_at, record_count=len(items), cache_hit=False),
    )
    return ensure_response_size(response)
