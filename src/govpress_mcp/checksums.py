from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class ChecksumRecord:
    news_item_id: str
    sha256: str
    revision: int
    fetched_at: str
    govpress_version: str | None = None
    govpress_commit: str | None = None
    source_format: str | None = None


class Store:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS checksums (
                news_item_id TEXT PRIMARY KEY,
                sha256 TEXT NOT NULL,
                revision INTEGER NOT NULL,
                fetched_at TEXT NOT NULL,
                govpress_version TEXT,
                govpress_commit TEXT,
                source_format TEXT
            )
            """
        )
        existing_columns = {
            row[1] for row in self._conn.execute("PRAGMA table_info(checksums)").fetchall()
        }
        for column in ("govpress_version", "govpress_commit", "source_format"):
            if column not in existing_columns:
                self._conn.execute(f"ALTER TABLE checksums ADD COLUMN {column} TEXT")
        self._conn.commit()

    def get(self, news_item_id: str) -> ChecksumRecord | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT news_item_id, sha256, revision, fetched_at,
                       govpress_version, govpress_commit, source_format
                FROM checksums
                WHERE news_item_id = ?
                """,
                (news_item_id,),
            ).fetchone()
        if row is None:
            return None
        return ChecksumRecord(*row)

    def put(
        self,
        *,
        news_item_id: str,
        sha256: str,
        revision: int,
        fetched_at: datetime,
        govpress_version: str | None = None,
        govpress_commit: str | None = None,
        source_format: str | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO checksums (
                    news_item_id, sha256, revision, fetched_at,
                    govpress_version, govpress_commit, source_format
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(news_item_id) DO UPDATE SET
                    sha256 = excluded.sha256,
                    revision = excluded.revision,
                    fetched_at = excluded.fetched_at,
                    govpress_version = excluded.govpress_version,
                    govpress_commit = excluded.govpress_commit,
                    source_format = excluded.source_format
                """,
                (
                    news_item_id,
                    sha256,
                    revision,
                    fetched_at.isoformat(),
                    govpress_version,
                    govpress_commit,
                    source_format,
                ),
            )
            self._conn.commit()


def open_store(path: Path) -> Store:
    path.parent.mkdir(parents=True, exist_ok=True)
    return Store(path)
