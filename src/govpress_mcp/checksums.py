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


class Store:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS checksums (
                news_item_id TEXT PRIMARY KEY,
                sha256 TEXT NOT NULL,
                revision INTEGER NOT NULL,
                fetched_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def get(self, news_item_id: str) -> ChecksumRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT news_item_id, sha256, revision, fetched_at FROM checksums WHERE news_item_id = ?",
                (news_item_id,),
            ).fetchone()
        if row is None:
            return None
        return ChecksumRecord(*row)

    def put(self, *, news_item_id: str, sha256: str, revision: int, fetched_at: datetime) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO checksums (news_item_id, sha256, revision, fetched_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(news_item_id) DO UPDATE SET
                    sha256 = excluded.sha256,
                    revision = excluded.revision,
                    fetched_at = excluded.fetched_at
                """,
                (news_item_id, sha256, revision, fetched_at.isoformat()),
            )
            self._conn.commit()


def open_store(path: Path) -> Store:
    path.parent.mkdir(parents=True, exist_ok=True)
    return Store(path)
