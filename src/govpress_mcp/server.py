from __future__ import annotations

import json
import time
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

from govpress_mcp.common import load_settings
from govpress_mcp.db import QdrantHTTPClient, SQLiteStore
from govpress_mcp.tools import (
    cross_check_ministries,
    fts_search,
    get_briefing,
    get_stats,
    list_briefings,
    search_briefing,
    trace_policy,
)
from govpress_mcp.usage import UsageLogger, render_usage_dashboard, summarize_usage


_SETTINGS = load_settings()
_STORE = SQLiteStore(_SETTINGS.db_path)
_QDRANT = QdrantHTTPClient(_SETTINGS.qdrant_url)
_USAGE_LOGGER = UsageLogger(_SETTINGS.usage_log_path)

app = FastMCP(
    "govpress-mcp",
    instructions=(
        "대한민국 정부 정책브리핑 보도자료를 검색하고 분석합니다. "
        "모든 도구는 읽기 전용이며, 원문 링크가 포함된 결과를 반환합니다."
    ),
    website_url="https://mcp.govpress.cloud",
    host="127.0.0.1",
    port=_SETTINGS.mcp_port,
    streamable_http_path="/mcp",
    json_response=True,
    stateless_http=True,
)

READ_ONLY_TOOL = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


def _run_logged(tool_name: str, arguments: dict[str, Any], fn: Callable[[], dict]) -> dict:
    started_at = time.perf_counter()
    response: dict[str, Any] | None = None
    exception: Exception | None = None
    try:
        response = fn()
        return response
    except Exception as exc:
        exception = exc
        raise
    finally:
        latency_ms = (time.perf_counter() - started_at) * 1000
        response_bytes = 0
        if response is not None:
            response_bytes = len(json.dumps(response, ensure_ascii=False, default=str).encode("utf-8"))
        _USAGE_LOGGER.log_tool_call(
            tool_name=tool_name,
            arguments=arguments,
            response=response,
            latency_ms=latency_ms,
            response_bytes=response_bytes,
            exception=exception,
        )


@app.tool(
    name="get_stats",
    title="전체 현황",
    description="Govpress 코퍼스와 색인, 벡터 저장소 통계를 조회합니다.",
    annotations=READ_ONLY_TOOL,
)
def get_stats_tool() -> dict:
    return _run_logged(
        "get_stats",
        {},
        lambda: get_stats(store=_STORE, qdrant=_QDRANT).to_dict(),
    )


@app.tool(
    name="get_briefing",
    title="문서 본문",
    description="단일 정책브리핑 보도자료를 메타데이터와 원문 링크 포함 Markdown으로 조회합니다.",
    annotations=READ_ONLY_TOOL,
)
def get_briefing_tool(id: str, include_metadata: bool = True, max_chars: int | None = None) -> dict:
    return _run_logged(
        "get_briefing",
        {"id": id, "include_metadata": include_metadata, "max_chars": max_chars},
        lambda: get_briefing(
            store=_STORE,
            data_root=_SETTINGS.data_root,
            id=id,
            include_metadata=include_metadata,
            max_chars=max_chars,
        ).to_dict(),
    )


@app.tool(
    name="list_briefings",
    title="문서 목록",
    description="날짜, 부처, 기관 유형, 원본 포맷 조건으로 정책브리핑 보도자료 목록을 조회합니다.",
    annotations=READ_ONLY_TOOL,
)
def list_briefings_tool(
    date_from: str | None = None,
    date_to: str | None = None,
    department: str | None = None,
    entity_type: str | None = None,
    source_format: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    return _run_logged(
        "list_briefings",
        {
            "date_from": date_from,
            "date_to": date_to,
            "department": department,
            "entity_type": entity_type,
            "source_format": source_format,
            "page": page,
            "page_size": page_size,
        },
        lambda: list_briefings(
            store=_STORE,
            date_from=date_from,
            date_to=date_to,
            department=department,
            entity_type=entity_type,
            source_format=source_format,
            page=page,
            page_size=page_size,
        ).to_dict(),
    )


@app.tool(
    name="fts_search",
    title="본문 검색",
    description="SQLite FTS5를 이용해 보도자료 본문을 키워드 검색하고 하이라이트 발췌문을 반환합니다.",
    annotations=READ_ONLY_TOOL,
)
def fts_search_tool(query: str, limit: int = 10) -> dict:
    return _run_logged(
        "fts_search",
        {"query": query, "limit": limit},
        lambda: fts_search(
            store=_STORE,
            query=query,
            limit=limit,
        ).to_dict(),
    )


@app.tool(
    name="search_briefing",
    title="유사 문서 검색",
    description="BGE-M3 임베딩과 Qdrant를 이용해 색인된 보도자료 청크를 의미 기반으로 검색합니다.",
    annotations=READ_ONLY_TOOL,
)
def search_briefing_tool(
    query: str,
    date_from: str | None = None,
    date_to: str | None = None,
    ministry: str | None = None,
    limit: int = 10,
) -> dict:
    return _run_logged(
        "search_briefing",
        {
            "query": query,
            "date_from": date_from,
            "date_to": date_to,
            "ministry": ministry,
            "limit": limit,
        },
        lambda: search_briefing(
            store=_STORE,
            qdrant=_QDRANT,
            tei_url=_SETTINGS.tei_url,
            query=query,
            date_from=date_from,
            date_to=date_to,
            ministry=ministry,
            limit=limit,
        ).to_dict(),
    )


@app.tool(
    name="cross_check_ministries",
    title="부처 비교",
    description="같은 주제를 여러 부처가 어떻게 설명하는지 비교하고 부처별 대표 결과를 반환합니다.",
    annotations=READ_ONLY_TOOL,
)
def cross_check_ministries_tool(
    topic: str,
    date_from: str | None = None,
    date_to: str | None = None,
    min_ministries: int = 2,
) -> dict:
    return _run_logged(
        "cross_check_ministries",
        {
            "topic": topic,
            "date_from": date_from,
            "date_to": date_to,
            "min_ministries": min_ministries,
        },
        lambda: cross_check_ministries(
            store=_STORE,
            qdrant=_QDRANT,
            tei_url=_SETTINGS.tei_url,
            topic=topic,
            date_from=date_from,
            date_to=date_to,
            min_ministries=min_ministries,
        ).to_dict(),
    )


@app.tool(
    name="trace_policy",
    title="흐름 보기",
    description="정책이 시간에 따라 어떻게 이어지는지 보여줍니다.",
    annotations=READ_ONLY_TOOL,
)
def trace_policy_tool(
    keyword: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    return _run_logged(
        "trace_policy",
        {
            "keyword": keyword,
            "date_from": date_from,
            "date_to": date_to,
        },
        lambda: trace_policy(
            store=_STORE,
            qdrant=_QDRANT,
            tei_url=_SETTINGS.tei_url,
            keyword=keyword,
            date_from=date_from,
            date_to=date_to,
        ).to_dict(),
    )


# compare_versions는 checksums history가 누적될 때까지 공개 액션 목록에서 숨긴다.


@app.custom_route("/dashboard", methods=["GET"], include_in_schema=False)
async def usage_dashboard(request: Request) -> HTMLResponse:
    summary = summarize_usage(_SETTINGS.usage_log_path)
    return HTMLResponse(render_usage_dashboard(summary))


@app.custom_route("/dashboard/usage.json", methods=["GET"], include_in_schema=False)
async def usage_dashboard_json(request: Request) -> JSONResponse:
    return JSONResponse(summarize_usage(_SETTINGS.usage_log_path))


def main_stdio() -> None:
    app.run(transport="stdio")


def main_sse() -> None:
    app.run(transport="streamable-http")


if __name__ == "__main__":
    main_sse()
