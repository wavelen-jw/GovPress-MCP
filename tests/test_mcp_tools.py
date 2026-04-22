from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from govpress_mcp import frontmatter
from govpress_mcp.db.qdrant import QdrantCollectionStats, QdrantSearchHit
from govpress_mcp.db.sqlite import SQLiteStore
from govpress_mcp.tools.cross import cross_check_ministries
from govpress_mcp.tools.fetch import get_briefing
from govpress_mcp.tools.listing import list_briefings
from govpress_mcp.tools.search import fts_search, search_briefing
from govpress_mcp.tools.stats import get_stats
from govpress_mcp.tools.trace import trace_policy
from govpress_mcp.tools.versions import compare_versions


class FakeQdrantClient:
    def collection_stats(self) -> QdrantCollectionStats:
        return QdrantCollectionStats(points_count=123, indexed_vectors_count=120, status="green")

    def search(self, vector: list[float], *, limit: int, score_threshold: float = 0.5) -> list[QdrantSearchHit]:
        return [
            QdrantSearchHit(
                chunk_id="a1_0000",
                news_item_id="a1",
                approve_date="2026-04-10T06:00:00",
                department="행정안전부",
                entity_type="central",
                score=0.91,
            ),
            QdrantSearchHit(
                chunk_id="a1_0001",
                news_item_id="a1",
                approve_date="2026-04-10T06:00:00",
                department="행정안전부",
                entity_type="central",
                score=0.82,
            ),
            QdrantSearchHit(
                chunk_id="b1_0000",
                news_item_id="b1",
                approve_date="2026-04-12T06:00:00",
                department="서울특별시",
                entity_type="metro",
                score=0.77,
            ),
        ]


def _seed_sqlite(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE doc_meta (
            news_item_id  TEXT PRIMARY KEY,
            title         TEXT NOT NULL,
            department    TEXT,
            approve_date  TEXT,
            entity_type   TEXT,
            source_url    TEXT,
            source_format TEXT,
            indexed_at    TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE indexed_docs (
            md_path TEXT PRIMARY KEY,
            md_mtime_ns INTEGER NOT NULL,
            md_size INTEGER NOT NULL,
            indexed_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE VIRTUAL TABLE briefing_fts USING fts5(
            news_item_id UNINDEXED,
            chunk_index UNINDEXED,
            body,
            tokenize='unicode61'
        );
        CREATE TABLE briefing_chunks_meta (
            chunk_id TEXT PRIMARY KEY,
            news_item_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            chunk_total INTEGER NOT NULL,
            approve_date TEXT NOT NULL,
            department TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            body TEXT NOT NULL
        );
        """
    )
    rows = [
        ("a1", "제목 하나", "행정안전부", "2026-04-10T06:00:00", "central", "https://example.com/a1", "hwpx"),
        ("a2", "제목 둘", "행정안전부", "2026-04-11T06:00:00", "central", "https://example.com/a2", "pdf"),
        ("b1", "제목 셋", "서울특별시", "2026-04-12T06:00:00", "metro", "https://example.com/b1", "hwpx"),
    ]
    conn.executemany(
        "INSERT INTO doc_meta (news_item_id, title, department, approve_date, entity_type, source_url, source_format) VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.executemany(
        "INSERT INTO indexed_docs (md_path, md_mtime_ns, md_size) VALUES (?, ?, ?)",
        [("data/md/2026/04/a1.md", 1, 1), ("data/md/2026/04/a2.md", 1, 1)],
    )
    conn.executemany(
        "INSERT INTO briefing_fts (news_item_id, chunk_index, body) VALUES (?, ?, ?)",
        [("a1", 0, "탄소중립 본문 하나"), ("a2", 0, "일반 본문 둘"), ("b1", 0, "탄소중립 서울특별시 본문")],
    )
    conn.executemany(
        "INSERT INTO briefing_chunks_meta (chunk_id, news_item_id, chunk_index, chunk_total, approve_date, department, entity_type, body) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("a1_0000", "a1", 0, 1, "2026-04-10T06:00:00", "행정안전부", "central", "탄소중립 관련 본문 하나"),
            ("a1_0001", "a1", 1, 2, "2026-04-10T06:00:00", "행정안전부", "central", "탄소중립 추가 본문"),
            ("b1_0000", "b1", 0, 1, "2026-04-12T06:00:00", "서울특별시", "metro", "서울 탄소중립 정책 본문"),
        ],
    )
    conn.commit()
    conn.close()


def _write_md(data_root: Path, news_item_id: str, approve_date: str, title: str, body: str, department: str, source_format: str) -> None:
    year = approve_date[:4]
    month = approve_date[5:7]
    md_path = data_root / "md" / year / month / f"{news_item_id}.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(
        frontmatter.prepend(
            body,
            {
                "id": news_item_id,
                "title": title,
                "department": department,
                "approve_date": approve_date,
                "entity_type": "central",
                "original_url": f"https://example.com/{news_item_id}",
                "sha256": "abc",
                "revision": 1,
                "govpress_version": "0.1.12",
                "govpress_commit": "969abb0f2af2",
                "source_format": source_format,
                "raw_path": f"data/raw/{year}/{month}/{news_item_id}.{source_format}",
            },
        ),
        encoding="utf-8",
    )


def test_get_stats() -> None:
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        db_path = root / "govpress.db"
        _seed_sqlite(db_path)
        store = SQLiteStore(db_path)

        response = get_stats(store=store, qdrant=FakeQdrantClient())

        assert response.error is None
        assert response.data is not None
        assert response.data["doc_count"] == 3
        assert response.data["indexed_docs"] == 2
        assert response.data["briefing_fts_rows"] == 3
        assert response.data["qdrant_points_count"] == 123
        assert len(json.dumps(response.to_dict(), ensure_ascii=False).encode("utf-8")) < 50 * 1024


def test_get_briefing() -> None:
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        data_root = root / "data"
        db_path = root / "govpress.db"
        _seed_sqlite(db_path)
        _write_md(
            data_root,
            "a1",
            "2026-04-10T06:00:00",
            "제목 하나",
            "서문\n\n## 본문\n" + ("가" * 500),
            "행정안전부",
            "hwpx",
        )
        store = SQLiteStore(db_path)

        response = get_briefing(store=store, data_root=data_root, id="a1", include_metadata=True, max_chars=120)

        assert response.error is None
        assert response.data is not None
        assert response.data["id"] == "a1"
        assert response.data["metadata"]["title"] == "제목 하나"
        assert "[...이하 생략" in response.data["body"]
        assert len(json.dumps(response.to_dict(), ensure_ascii=False).encode("utf-8")) < 50 * 1024


def test_list_briefings() -> None:
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        db_path = root / "govpress.db"
        _seed_sqlite(db_path)
        store = SQLiteStore(db_path)

        response = list_briefings(
            store=store,
            department="행정안전부",
            page=1,
            page_size=1,
        )

        assert response.error is None
        assert response.data is not None
        assert response.data["total"] == 2
        assert response.data["page_size"] == 1
        assert response.data["has_more"] is True
        assert len(response.data["items"]) == 1
        assert response.data["items"][0]["department"] == "행정안전부"
        assert len(json.dumps(response.to_dict(), ensure_ascii=False).encode("utf-8")) < 50 * 1024


def test_fts_search() -> None:
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        db_path = root / "govpress.db"
        _seed_sqlite(db_path)
        store = SQLiteStore(db_path)

        response = fts_search(store=store, query="탄소중립", limit=5)

        assert response.error is None
        assert response.data is not None
        assert len(response.data["items"]) >= 1
        assert response.data["items"][0]["snippet"]
        assert len(json.dumps(response.to_dict(), ensure_ascii=False).encode("utf-8")) < 50 * 1024


def test_search_briefing() -> None:
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        db_path = root / "govpress.db"
        _seed_sqlite(db_path)
        store = SQLiteStore(db_path)

        from govpress_mcp.tools import search as search_module

        original_embed = search_module._embed_query
        try:
            search_module._embed_query = lambda tei_url, query: [0.1, 0.2, 0.3]
            response = search_briefing(
                store=store,
                qdrant=FakeQdrantClient(),
                tei_url="http://localhost:18080",
                query="탄소중립",
                limit=5,
            )
        finally:
            search_module._embed_query = original_embed

        assert response.error is None
        assert response.data is not None
        assert len(response.data["items"]) == 2
        assert response.data["items"][0]["news_item_id"] == "a1"
        assert response.data["items"][0]["score"] >= response.data["items"][1]["score"]
        assert len(json.dumps(response.to_dict(), ensure_ascii=False).encode("utf-8")) < 50 * 1024


def test_cross_check_ministries() -> None:
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        db_path = root / "govpress.db"
        _seed_sqlite(db_path)
        store = SQLiteStore(db_path)

        from govpress_mcp.tools import search as search_module

        original_embed = search_module._embed_query
        try:
            search_module._embed_query = lambda tei_url, query: [0.1, 0.2, 0.3]
            response = cross_check_ministries(
                store=store,
                qdrant=FakeQdrantClient(),
                tei_url="http://localhost:18080",
                topic="탄소중립",
                min_ministries=2,
            )
        finally:
            search_module._embed_query = original_embed

        assert response.error is None
        assert response.data is not None
        assert len(response.data["items"]) == 2
        assert response.data["enough_ministries"] is True
        assert len(json.dumps(response.to_dict(), ensure_ascii=False).encode("utf-8")) < 50 * 1024


def test_trace_policy() -> None:
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        db_path = root / "govpress.db"
        _seed_sqlite(db_path)
        store = SQLiteStore(db_path)

        from govpress_mcp.tools import search as search_module

        original_embed = search_module._embed_query
        try:
            search_module._embed_query = lambda tei_url, query: [0.1, 0.2, 0.3]
            response = trace_policy(
                store=store,
                qdrant=FakeQdrantClient(),
                tei_url="http://localhost:18080",
                keyword="탄소중립",
            )
        finally:
            search_module._embed_query = original_embed

        assert response.error is None
        assert response.data is not None
        nodes = response.data["nodes"]
        assert len(nodes) == 2
        assert nodes[0]["approve_date"] <= nodes[1]["approve_date"]
        assert len(json.dumps(response.to_dict(), ensure_ascii=False).encode("utf-8")) < 50 * 1024


def test_compare_versions() -> None:
    response = compare_versions(briefing_id="156445671")

    assert response.error is None
    assert response.data is not None
    assert response.data["experimental"] is True
    assert response.data["versions"] == []
    assert response.data["note"] == "checksums_history 누적 후 활성화 예정"
    assert len(json.dumps(response.to_dict(), ensure_ascii=False).encode("utf-8")) < 50 * 1024
