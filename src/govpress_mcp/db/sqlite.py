from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from govpress_mcp import frontmatter


@dataclass(frozen=True)
class BriefingMeta:
    news_item_id: str
    title: str
    department: str | None
    approve_date: str | None
    entity_type: str | None
    source_url: str | None
    source_format: str | None


class SQLiteStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def connect(self, *, readonly: bool = True) -> sqlite3.Connection:
        if readonly:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        else:
            conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def stats(self) -> dict[str, Any]:
        with self.connect() as conn:
            doc_count = self._scalar(conn, "SELECT COUNT(*) FROM doc_meta")
            indexed_count = self._scalar(conn, "SELECT COUNT(*) FROM indexed_docs")
            try:
                fts_count = self._scalar(conn, "SELECT COUNT(*) FROM briefing_chunks_meta")
            except sqlite3.OperationalError:
                fts_count = self._scalar(conn, "SELECT COUNT(*) FROM briefing_fts")
            date_range = conn.execute(
                "SELECT MIN(approve_date) AS min_date, MAX(approve_date) AS max_date FROM doc_meta"
            ).fetchone()
            source_formats = self._rows_to_dict(
                conn.execute(
                    "SELECT source_format AS key, COUNT(*) AS value FROM doc_meta GROUP BY source_format ORDER BY value DESC"
                ).fetchall()
            )
            entity_types = self._rows_to_dict(
                conn.execute(
                    "SELECT entity_type AS key, COUNT(*) AS value FROM doc_meta GROUP BY entity_type ORDER BY value DESC"
                ).fetchall()
            )
            departments = self._rows_to_dict(
                conn.execute(
                    "SELECT department AS key, COUNT(*) AS value FROM doc_meta GROUP BY department ORDER BY value DESC LIMIT 10"
                ).fetchall()
            )
        return {
            "doc_count": doc_count,
            "indexed_docs": indexed_count,
            "briefing_fts_rows": fts_count,
            "approve_date_min": date_range["min_date"] if date_range else None,
            "approve_date_max": date_range["max_date"] if date_range else None,
            "by_source_format": source_formats,
            "by_entity_type": entity_types,
            "top_departments": departments,
        }

    def get_briefing_meta(self, news_item_id: str) -> BriefingMeta | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT news_item_id, title, department, approve_date, entity_type, source_url, source_format
                FROM doc_meta
                WHERE news_item_id = ?
                """,
                (news_item_id,),
            ).fetchone()
        if row is None:
            return None
        return BriefingMeta(
            news_item_id=row["news_item_id"],
            title=row["title"],
            department=row["department"],
            approve_date=row["approve_date"],
            entity_type=row["entity_type"],
            source_url=row["source_url"],
            source_format=row["source_format"],
        )

    def list_briefings(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        department: str | None = None,
        entity_type: str | None = None,
        source_format: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[int, list[dict[str, Any]]]:
        where: list[str] = []
        params: list[Any] = []
        if date_from:
            where.append("approve_date >= ?")
            params.append(date_from)
        if date_to:
            where.append("approve_date <= ?")
            params.append(date_to)
        if department:
            where.append("department = ?")
            params.append(department)
        if entity_type:
            where.append("entity_type = ?")
            params.append(entity_type)
        if source_format:
            where.append("source_format = ?")
            params.append(source_format)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        offset = max(page - 1, 0) * page_size
        with self.connect() as conn:
            total = self._scalar(conn, f"SELECT COUNT(*) FROM doc_meta {where_sql}", params)
            rows = conn.execute(
                f"""
                SELECT news_item_id, title, department, approve_date, entity_type, source_url, source_format
                FROM doc_meta
                {where_sql}
                ORDER BY approve_date DESC, news_item_id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, offset],
            ).fetchall()
        return total, [dict(row) for row in rows]

    def fts_search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        sql = """
            SELECT
                f.news_item_id,
                f.chunk_index,
                snippet(briefing_fts, 2, '<mark>', '</mark>', '...', 24) AS snippet,
                bm25(briefing_fts) AS rank,
                d.title,
                d.department,
                d.approve_date,
                d.source_url,
                d.source_format
            FROM briefing_fts AS f
            JOIN doc_meta AS d ON d.news_item_id = f.news_item_id
            WHERE briefing_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """
        phrase_query = '"' + query.replace('"', '""') + '"'
        with self.connect() as conn:
            try:
                rows = conn.execute(sql, (query, limit * 5)).fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(sql, (phrase_query, limit * 5)).fetchall()
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            news_item_id = str(row["news_item_id"])
            if news_item_id in seen:
                continue
            seen.add(news_item_id)
            deduped.append(dict(row))
            if len(deduped) >= limit:
                break
        return deduped

    def get_doc_meta_map(self, news_item_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not news_item_ids:
            return {}
        placeholders = ",".join("?" for _ in news_item_ids)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT news_item_id, title, department, approve_date, entity_type, source_url, source_format
                FROM doc_meta
                WHERE news_item_id IN ({placeholders})
                """,
                news_item_ids,
            ).fetchall()
        return {str(row["news_item_id"]): dict(row) for row in rows}

    def get_chunk_bodies(self, chunk_ids: list[str]) -> dict[str, str]:
        if not chunk_ids:
            return {}
        placeholders = ",".join("?" for _ in chunk_ids)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT chunk_id, body FROM briefing_chunks_meta WHERE chunk_id IN ({placeholders})",
                chunk_ids,
            ).fetchall()
        return {str(row["chunk_id"]): str(row["body"]) for row in rows}

    def resolve_md_path(self, data_root: Path, meta: BriefingMeta) -> Path:
        if not meta.approve_date:
            raise ValueError("approve_date_missing")
        year = meta.approve_date[:4]
        month = meta.approve_date[5:7]
        return data_root / "md" / year / month / f"{meta.news_item_id}.md"

    def read_briefing(self, data_root: Path, news_item_id: str) -> tuple[BriefingMeta, dict[str, str], str]:
        meta = self.get_briefing_meta(news_item_id)
        if meta is None:
            raise FileNotFoundError(news_item_id)
        md_path = self.resolve_md_path(data_root, meta)
        document = md_path.read_text(encoding="utf-8")
        parsed_frontmatter, body = frontmatter.parse(document)
        return meta, parsed_frontmatter, body

    @staticmethod
    def _scalar(conn: sqlite3.Connection, sql: str, params: list[Any] | tuple[Any, ...] | None = None) -> int:
        row = conn.execute(sql, params or []).fetchone()
        return int(row[0]) if row is not None else 0

    @staticmethod
    def _rows_to_dict(rows: list[sqlite3.Row]) -> dict[str, int]:
        result: dict[str, int] = {}
        for row in rows:
            key = row["key"] if row["key"] is not None else "unknown"
            result[str(key)] = int(row["value"])
        return result
