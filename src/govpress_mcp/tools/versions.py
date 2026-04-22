from __future__ import annotations

import time

from govpress_mcp.common import ToolResponse, ensure_response_size, make_meta


def compare_versions(*, briefing_id: str, revision: int | None = None) -> ToolResponse:
    started_at = time.perf_counter()
    response = ToolResponse(
        data={
            "briefing_id": briefing_id,
            "revision": revision,
            "experimental": True,
            "note": "checksums_history 누적 후 활성화 예정",
            "versions": [],
        },
        meta=make_meta(started_at, record_count=0, cache_hit=False),
    )
    return ensure_response_size(response)
