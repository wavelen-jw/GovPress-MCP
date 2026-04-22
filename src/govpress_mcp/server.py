from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from govpress_mcp.common import load_settings
from govpress_mcp.db import QdrantHTTPClient, SQLiteStore
from govpress_mcp.tools import (
    compare_versions,
    cross_check_ministries,
    fts_search,
    get_briefing,
    get_stats,
    list_briefings,
    search_briefing,
    trace_policy,
)


_SETTINGS = load_settings()
_STORE = SQLiteStore(_SETTINGS.db_path)
_QDRANT = QdrantHTTPClient(_SETTINGS.qdrant_url)

app = FastMCP(
    "govpress-mcp",
    host="127.0.0.1",
    port=_SETTINGS.mcp_port,
    streamable_http_path="/mcp",
    json_response=True,
    stateless_http=True,
)


@app.tool(name="get_stats")
def get_stats_tool() -> dict:
    return get_stats(store=_STORE, qdrant=_QDRANT).to_dict()


@app.tool(name="get_briefing")
def get_briefing_tool(id: str, include_metadata: bool = True, max_chars: int | None = None) -> dict:
    return get_briefing(
        store=_STORE,
        data_root=_SETTINGS.data_root,
        id=id,
        include_metadata=include_metadata,
        max_chars=max_chars,
    ).to_dict()


@app.tool(name="list_briefings")
def list_briefings_tool(
    date_from: str | None = None,
    date_to: str | None = None,
    department: str | None = None,
    entity_type: str | None = None,
    source_format: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    return list_briefings(
        store=_STORE,
        date_from=date_from,
        date_to=date_to,
        department=department,
        entity_type=entity_type,
        source_format=source_format,
        page=page,
        page_size=page_size,
    ).to_dict()


@app.tool(name="fts_search")
def fts_search_tool(query: str, limit: int = 10) -> dict:
    return fts_search(
        store=_STORE,
        query=query,
        limit=limit,
    ).to_dict()


@app.tool(name="search_briefing")
def search_briefing_tool(
    query: str,
    date_from: str | None = None,
    date_to: str | None = None,
    ministry: str | None = None,
    limit: int = 10,
) -> dict:
    return search_briefing(
        store=_STORE,
        qdrant=_QDRANT,
        tei_url=_SETTINGS.tei_url,
        query=query,
        date_from=date_from,
        date_to=date_to,
        ministry=ministry,
        limit=limit,
    ).to_dict()


@app.tool(name="cross_check_ministries")
def cross_check_ministries_tool(
    topic: str,
    date_from: str | None = None,
    date_to: str | None = None,
    min_ministries: int = 2,
) -> dict:
    return cross_check_ministries(
        store=_STORE,
        qdrant=_QDRANT,
        tei_url=_SETTINGS.tei_url,
        topic=topic,
        date_from=date_from,
        date_to=date_to,
        min_ministries=min_ministries,
    ).to_dict()


@app.tool(name="trace_policy")
def trace_policy_tool(
    keyword: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    return trace_policy(
        store=_STORE,
        qdrant=_QDRANT,
        tei_url=_SETTINGS.tei_url,
        keyword=keyword,
        date_from=date_from,
        date_to=date_to,
    ).to_dict()


@app.tool(name="compare_versions")
def compare_versions_tool(briefing_id: str, revision: int | None = None) -> dict:
    return compare_versions(
        briefing_id=briefing_id,
        revision=revision,
    ).to_dict()


def main_stdio() -> None:
    app.run(transport="stdio")


def main_sse() -> None:
    app.run(transport="streamable-http")


if __name__ == "__main__":
    main_sse()
