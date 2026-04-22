from __future__ import annotations

import time

from govpress_mcp.common import ToolResponse, ensure_response_size, make_meta, smart_truncate
from govpress_mcp.db.sqlite import SQLiteStore


def get_briefing(
    *,
    store: SQLiteStore,
    data_root,
    id: str,
    include_metadata: bool = True,
    max_chars: int | None = None,
) -> ToolResponse:
    started_at = time.perf_counter()
    try:
        meta, parsed_frontmatter, body = store.read_briefing(data_root, id)
    except FileNotFoundError:
        return ToolResponse(
            data=None,
            error="not_found",
            meta=make_meta(started_at, record_count=0, cache_hit=False),
        )

    rendered_body = smart_truncate(body, max_chars) if max_chars else body
    payload = {
        "id": meta.news_item_id,
        "body": rendered_body,
        "source_url": meta.source_url,
        "source_format": meta.source_format,
    }
    if include_metadata:
        payload["metadata"] = parsed_frontmatter
    response = ToolResponse(
        data=payload,
        meta=make_meta(started_at, record_count=1, cache_hit=False),
    )
    return ensure_response_size(response)
