from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import sqlite3
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from govpress_mcp import frontmatter, paths

UTC = timezone.utc
COLLECTION_NAME = "briefing_chunks"
EMBED_DIM = 1024
EMBED_BATCH_SIZE = 64
EMBED_INFLIGHT = 4
MAX_TOKENS = 512
OVERLAP_TOKENS = 64
CHECKPOINT_NAME = "derive-hot-checkpoint.json"
QDRANT_NAMESPACE = uuid.UUID("73aef6b7-30d6-4ce0-b985-cd3904f42fe7")


@dataclass
class Chunk:
    chunk_id: str
    news_item_id: str
    approve_date: str
    department: str
    entity_type: str
    chunk_index: int
    chunk_total: int
    body: str


@dataclass
class RunStats:
    md_files: int = 0
    chunks: int = 0
    embedding_seconds: float = 0.0
    failures: int = 0
    fts_tokenizer: str = "unicode61 trigram"
    wall_clock_seconds: float = 0.0


@dataclass
class PreparedDoc:
    index: int
    md_path: Path
    chunks: list[Chunk]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Derive Qdrant + FTS5 hot indexes from Markdown corpus.")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--qdrant-url", default="http://localhost:6333")
    parser.add_argument("--tei-url", default="http://localhost:8080")
    parser.add_argument("--db", type=Path, default=Path("data/govpress.db"))
    parser.add_argument("--checkpoint", type=int, default=1000)
    parser.add_argument("--incremental", action="store_true")
    parser.add_argument("--sample", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started = time.perf_counter()
    data_root = _canonical_data_root(args.data_root)
    db_path = args.db if args.db.is_absolute() else Path.cwd() / args.db
    checkpoint_path = data_root / "fetch-log" / CHECKPOINT_NAME
    paths.ensure_dirs(data_root)

    _check_health(args.tei_url)
    _ensure_qdrant_collection(args.qdrant_url)

    conn = sqlite3.connect(db_path, timeout=60)
    md_files = sorted((data_root / "md").rglob("*.md"))
    if args.incremental:
        md_files = [p for p in md_files if _needs_reindex(conn, p)]
    if args.sample is not None:
        md_files = md_files[: args.sample]
    tokenizer = _ensure_sqlite_schema(conn)
    stats = RunStats(md_files=len(md_files), fts_tokenizer=tokenizer)
    failures: list[dict[str, Any]] = []
    _process_md_files(
        md_files=md_files,
        tei_url=args.tei_url,
        qdrant_url=args.qdrant_url,
        conn=conn,
        checkpoint=args.checkpoint,
        checkpoint_path=checkpoint_path,
        stats=stats,
        failures=failures,
        enable_checkpoint_writes=args.sample is None,
    )

    conn.commit()
    vector_count = _qdrant_points_count(args.qdrant_url)
    fts_rows = conn.execute("SELECT COUNT(*) FROM briefing_fts").fetchone()[0]
    if args.sample is None:
        _write_checkpoint(checkpoint_path, md_files[-1] if md_files else None)
    stats.wall_clock_seconds = time.perf_counter() - started
    if args.sample is None:
        _write_report(
            data_root.parent / "docs" / "derive-hot-report.md",
            stats=stats,
            vector_count=vector_count,
            fts_rows=fts_rows,
            failures=failures,
            incremental=args.incremental,
            checkpoint_path=checkpoint_path,
        )
    conn.close()
    return 0


def _process_md_files(
    *,
    md_files: list[Path],
    tei_url: str,
    qdrant_url: str,
    conn: sqlite3.Connection,
    checkpoint: int,
    checkpoint_path: Path,
    stats: RunStats,
    failures: list[dict[str, Any]],
    enable_checkpoint_writes: bool,
) -> None:
    if not md_files:
        return

    with concurrent.futures.ThreadPoolExecutor(max_workers=EMBED_INFLIGHT) as executor:
        pending: dict[int, tuple[PreparedDoc, concurrent.futures.Future[tuple[list[list[float]], float]]]] = {}
        next_submit = 0
        next_write = 0

        while next_write < len(md_files):
            while next_submit < len(md_files) and len(pending) < EMBED_INFLIGHT:
                md_path = md_files[next_submit]
                chunks = _build_chunks_for_md(md_path)
                prepared = PreparedDoc(index=next_submit, md_path=md_path, chunks=chunks)
                future = executor.submit(_embed_chunks, tei_url, chunks)
                pending[next_submit] = (prepared, future)
                next_submit += 1

            prepared, future = pending.pop(next_write)
            try:
                vectors, embed_seconds = future.result()
                stats.embedding_seconds += embed_seconds
                _upsert_qdrant(qdrant_url, prepared.chunks, vectors)
                _upsert_sqlite(conn, prepared.md_path, prepared.chunks)
                stats.chunks += len(prepared.chunks)
            except Exception as exc:  # noqa: BLE001
                stats.failures += 1
                failures.append({"md_path": str(prepared.md_path), "error": f"{type(exc).__name__}: {exc}"})

            processed = next_write + 1
            if enable_checkpoint_writes and processed % checkpoint == 0:
                conn.commit()
                _write_checkpoint(checkpoint_path, prepared.md_path)
            next_write += 1


def _canonical_data_root(data_root: Path) -> Path:
    resolved = data_root.expanduser().resolve()
    repo_data = (Path.cwd() / "data").resolve()
    return repo_data if resolved != repo_data else resolved


def _check_health(tei_url: str) -> None:
    request = urllib.request.Request(f"{tei_url.rstrip('/')}/health")
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"TEI health check failed: {response.status}")


def _ensure_qdrant_collection(qdrant_url: str) -> None:
    collection_url = f"{qdrant_url.rstrip('/')}/collections/{COLLECTION_NAME}"
    request = urllib.request.Request(collection_url)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status == 200:
                return
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    payload = {
        "vectors": {
            "size": EMBED_DIM,
            "distance": "Cosine",
        },
        "hnsw_config": {
            "m": 16,
            "ef_construct": 200,
        },
    }
    _qdrant_json(
        collection_url,
        payload,
        method="PUT",
    )
    for field_name in ("news_item_id", "approve_date", "entity_type", "department"):
        _qdrant_json(
            f"{collection_url}/index",
            {"field_name": field_name, "field_schema": "keyword"},
            method="PUT",
        )


def _ensure_sqlite_schema(conn: sqlite3.Connection) -> str:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS briefing_chunks_meta (
            chunk_id TEXT PRIMARY KEY,
            news_item_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            chunk_total INTEGER NOT NULL,
            approve_date TEXT NOT NULL,
            department TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            body TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS indexed_docs (
            md_path TEXT PRIMARY KEY,
            md_mtime_ns INTEGER NOT NULL,
            md_size INTEGER NOT NULL,
            chunk_count INTEGER NOT NULL,
            indexed_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS doc_meta (
            news_item_id  TEXT PRIMARY KEY,
            title         TEXT NOT NULL,
            department    TEXT,
            approve_date  TEXT,
            entity_type   TEXT,
            source_url    TEXT,
            source_format TEXT,
            indexed_at    TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_meta_date ON doc_meta(approve_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_meta_dept ON doc_meta(department)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_meta_etype ON doc_meta(entity_type)")
    tokenizer = _ensure_fts_table(conn)
    conn.commit()
    return tokenizer


def _ensure_fts_table(conn: sqlite3.Connection) -> str:
    for tokenizer in ("unicode61 trigram", "trigram"):
        try:
            conn.execute(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS briefing_fts USING fts5(
                    news_item_id UNINDEXED,
                    chunk_index UNINDEXED,
                    body,
                    tokenize='{tokenizer}'
                )
                """
            )
            return tokenizer
        except sqlite3.OperationalError:
            conn.execute("DROP TABLE IF EXISTS briefing_fts")
            continue
    raise RuntimeError("지원 가능한 FTS5 tokenizer를 찾지 못했습니다.")


def _needs_reindex(conn: sqlite3.Connection, md_path: Path) -> bool:
    stat = md_path.stat()
    row = conn.execute(
        "SELECT md_mtime_ns, md_size FROM indexed_docs WHERE md_path = ?",
        (str(md_path),),
    ).fetchone()
    if row is None:
        return True
    return row[0] != stat.st_mtime_ns or row[1] != stat.st_size


def _build_chunks_for_md(md_path: Path) -> list[Chunk]:
    fm, body = frontmatter.parse(md_path.read_text(encoding="utf-8"))
    paragraphs = [part.strip() for part in body.split("\n\n") if part.strip()]
    windows = _paragraph_windows(paragraphs)
    chunks: list[Chunk] = []
    total = len(windows)
    for idx, paragraph_group in enumerate(windows):
        chunk_id = f"{fm['id']}_{idx:04d}"
        body_text = "\n\n".join(paragraph_group).strip()
        if not body_text:
            continue
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                news_item_id=fm["id"],
                approve_date=fm["approve_date"],
                department=fm["department"],
                entity_type=fm["entity_type"],
                chunk_index=idx,
                chunk_total=total,
                body=body_text,
            )
        )
    return chunks


def _paragraph_windows(paragraphs: list[str]) -> list[list[str]]:
    if not paragraphs:
        return [[]]
    token_counts = [_estimate_tokens(p) for p in paragraphs]
    windows: list[list[str]] = []
    i = 0
    while i < len(paragraphs):
        current: list[str] = []
        total_tokens = 0
        j = i
        while j < len(paragraphs):
            count = token_counts[j]
            if current and total_tokens + count > MAX_TOKENS:
                break
            current.append(paragraphs[j])
            total_tokens += count
            j += 1
        if not current:
            current = [paragraphs[i]]
            j = i + 1
        windows.append(current)
        if j >= len(paragraphs):
            break
        overlap = 0
        back = j - 1
        while back >= i and overlap < OVERLAP_TOKENS:
            overlap += token_counts[back]
            back -= 1
        i = max(back + 1, i + 1)
    return windows


def _estimate_tokens(text: str) -> int:
    rough = max(1, math.ceil(len(text) / 4))
    return rough


def _embed_chunks(tei_url: str, chunks: list[Chunk]) -> tuple[list[list[float]], float]:
    vectors: list[list[float]] = []
    started = time.perf_counter()
    texts = [chunk.body for chunk in chunks]
    for offset in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[offset : offset + EMBED_BATCH_SIZE]
        response = _tei_embed(tei_url, batch)
        if len(response) != len(batch):
            raise RuntimeError("TEI embed response size mismatch")
        vectors.extend(response)
    return vectors, time.perf_counter() - started


def _tei_embed(tei_url: str, inputs: list[str]) -> list[list[float]]:
    payload = json.dumps({"inputs": inputs}).encode("utf-8")
    request = urllib.request.Request(
        f"{tei_url.rstrip('/')}/embed",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        data = json.loads(response.read().decode("utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "embeddings" in data:
        return data["embeddings"]
    raise RuntimeError("Unexpected TEI response shape")


def _upsert_qdrant(qdrant_url: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
    points = []
    for chunk, vector in zip(chunks, vectors, strict=True):
        points.append(
            {
                "id": str(uuid.uuid5(QDRANT_NAMESPACE, chunk.chunk_id)),
                "vector": vector,
                "payload": {
                    "chunk_id": chunk.chunk_id,
                    "news_item_id": chunk.news_item_id,
                    "approve_date": chunk.approve_date,
                    "department": chunk.department,
                    "entity_type": chunk.entity_type,
                    "chunk_index": chunk.chunk_index,
                    "chunk_total": chunk.chunk_total,
                },
            }
        )
    _qdrant_json(
        f"{qdrant_url.rstrip('/')}/collections/{COLLECTION_NAME}/points?wait=true",
        {"points": points},
        method="PUT",
    )


def _upsert_sqlite(conn: sqlite3.Connection, md_path: Path, chunks: list[Chunk]) -> None:
    fm = frontmatter.parse(md_path.read_text(encoding="utf-8"))[0]
    news_item_id = chunks[0].news_item_id if chunks else fm["id"]
    conn.execute("DELETE FROM briefing_chunks_meta WHERE news_item_id = ?", (news_item_id,))
    conn.execute("DELETE FROM briefing_fts WHERE news_item_id = ?", (news_item_id,))
    for chunk in chunks:
        conn.execute(
            """
            INSERT OR REPLACE INTO briefing_chunks_meta (
                chunk_id, news_item_id, chunk_index, chunk_total,
                approve_date, department, entity_type, body
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk.chunk_id,
                chunk.news_item_id,
                chunk.chunk_index,
                chunk.chunk_total,
                chunk.approve_date,
                chunk.department,
                chunk.entity_type,
                chunk.body,
            ),
        )
        conn.execute(
            "INSERT INTO briefing_fts (news_item_id, chunk_index, body) VALUES (?, ?, ?)",
            (chunk.news_item_id, chunk.chunk_index, chunk.body),
        )
    stat = md_path.stat()
    conn.execute(
        """
        INSERT INTO indexed_docs (md_path, md_mtime_ns, md_size, chunk_count, indexed_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(md_path) DO UPDATE SET
            md_mtime_ns = excluded.md_mtime_ns,
            md_size = excluded.md_size,
            chunk_count = excluded.chunk_count,
            indexed_at = excluded.indexed_at
        """,
        (
            str(md_path),
            stat.st_mtime_ns,
            stat.st_size,
            len(chunks),
            datetime.now(UTC).isoformat(),
        ),
    )
    _upsert_doc_meta(conn, fm)


def _upsert_doc_meta(conn: sqlite3.Connection, fm: dict[str, str]) -> None:
    conn.execute(
        """
        INSERT INTO doc_meta (
            news_item_id, title, department, approve_date,
            entity_type, source_url, source_format, indexed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(news_item_id) DO UPDATE SET
            title = excluded.title,
            department = excluded.department,
            approve_date = excluded.approve_date,
            entity_type = excluded.entity_type,
            source_url = excluded.source_url,
            source_format = excluded.source_format,
            indexed_at = excluded.indexed_at
        """,
        (
            fm["id"],
            fm["title"],
            fm.get("department"),
            fm.get("approve_date"),
            fm.get("entity_type"),
            fm.get("original_url"),
            fm.get("source_format"),
            datetime.now(UTC).isoformat(),
        ),
    )


def _qdrant_points_count(qdrant_url: str) -> int:
    request = urllib.request.Request(f"{qdrant_url.rstrip('/')}/collections/{COLLECTION_NAME}")
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    return int(data["result"]["points_count"])


def _qdrant_json(url: str, payload: dict[str, Any], *, method: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def _write_checkpoint(checkpoint_path: Path, md_path: Path | None) -> None:
    payload = {
        "updated_at": datetime.now(UTC).isoformat(),
        "last_md_path": str(md_path) if md_path is not None else None,
    }
    paths.atomic_write_text(checkpoint_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _write_report(
    report_path: Path,
    *,
    stats: RunStats,
    vector_count: int,
    fts_rows: int,
    failures: list[dict[str, Any]],
    incremental: bool,
    checkpoint_path: Path,
) -> None:
    lines = [
        "# Derive Hot Report",
        "",
        f"- mode: {'incremental' if incremental else 'full'}",
        f"- processed_md_files: `{stats.md_files}`",
        f"- total_chunks: `{stats.chunks}`",
        f"- wall_clock_seconds: `{stats.wall_clock_seconds:.2f}`",
        f"- embedding_seconds: `{stats.embedding_seconds:.2f}`",
        f"- qdrant_points: `{vector_count}`",
        f"- fts5_rows: `{fts_rows}`",
        f"- fts5_tokenizer: `{stats.fts_tokenizer}`",
        f"- failures: `{stats.failures}`",
        f"- checkpoint: `{checkpoint_path}`",
    ]
    if failures:
        lines.extend(["", "## Failures", ""])
        for failure in failures[:100]:
            lines.append(f"- `{failure['md_path']}`: {failure['error']}")
    paths.atomic_write_text(report_path, "\n".join(lines) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
