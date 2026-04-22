from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from govpress_mcp import derive_hot, frontmatter, paths


def test_paragraph_windows_overlap() -> None:
    paragraphs = ["a" * 1000, "b" * 1000, "c" * 1000]
    windows = derive_hot._paragraph_windows(paragraphs)

    assert len(windows) >= 2
    assert windows[0]
    assert windows[1]


def test_build_chunks_for_md() -> None:
    with TemporaryDirectory() as tmp_dir:
        data_root = Path(tmp_dir) / "data"
        paths.ensure_dirs(data_root)
        md_path = data_root / "md" / "2026" / "04" / "x.md"
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(
            frontmatter.prepend(
                "para1\n\npara2\n\npara3\n",
                {
                    "id": "x",
                    "title": "제목",
                    "department": "행정안전부",
                    "approve_date": "2026-04-10T06:00:00",
                    "entity_type": "central",
                    "original_url": "https://example.com/x",
                    "sha256": "abc",
                    "revision": 1,
                    "govpress_version": "0.1.12",
                    "govpress_commit": "abcdef123456",
                    "source_format": "hwpx",
                    "raw_path": "data/raw/2026/04/x.hwpx",
                },
            ),
            encoding="utf-8",
        )

        chunks = derive_hot._build_chunks_for_md(md_path)

        assert len(chunks) >= 1
        assert chunks[0].chunk_id == "x_0000"
        assert chunks[0].news_item_id == "x"


def test_build_chunks_skips_empty_body() -> None:
    with TemporaryDirectory() as tmp_dir:
        data_root = Path(tmp_dir) / "data"
        paths.ensure_dirs(data_root)
        md_path = data_root / "md" / "2026" / "04" / "empty.md"
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(
            frontmatter.prepend(
                "\n\n   \n\n",
                {
                    "id": "empty",
                    "title": "빈문서",
                    "department": "행정안전부",
                    "approve_date": "2026-04-10T06:00:00",
                    "entity_type": "central",
                    "original_url": "https://example.com/empty",
                    "sha256": "abc",
                    "revision": 1,
                    "govpress_version": "0.1.12",
                    "govpress_commit": "abcdef123456",
                    "source_format": "hwpx",
                    "raw_path": "data/raw/2026/04/empty.hwpx",
                },
            ),
            encoding="utf-8",
        )

        chunks = derive_hot._build_chunks_for_md(md_path)

        assert chunks == []


def test_sqlite_upsert_and_incremental_check() -> None:
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        data_root = root / "data"
        paths.ensure_dirs(data_root)
        db_path = root / "govpress.db"
        conn = sqlite3.connect(db_path)
        derive_hot._ensure_sqlite_schema(conn)

        md_path = data_root / "md" / "2026" / "04" / "x.md"
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(
            frontmatter.prepend(
                "body\n",
                {
                    "id": "x",
                    "title": "제목",
                    "department": "행정안전부",
                    "approve_date": "2026-04-10T06:00:00",
                    "entity_type": "central",
                    "original_url": "https://example.com/x",
                    "sha256": "abc",
                    "revision": 1,
                    "govpress_version": "0.1.12",
                    "govpress_commit": "abcdef123456",
                    "source_format": "hwpx",
                    "raw_path": "data/raw/2026/04/x.hwpx",
                },
            ),
            encoding="utf-8",
        )

        chunks = derive_hot._build_chunks_for_md(md_path)
        derive_hot._upsert_sqlite(conn, md_path, chunks)
        conn.commit()

        assert derive_hot._needs_reindex(conn, md_path) is False
        row = conn.execute("SELECT COUNT(*) FROM briefing_fts").fetchone()
        assert row is not None
        assert row[0] == len(chunks)
        doc_meta = conn.execute(
            """
            SELECT news_item_id, title, department, approve_date, entity_type, source_url, source_format
            FROM doc_meta
            WHERE news_item_id = ?
            """,
            ("x",),
        ).fetchone()
        assert doc_meta == (
            "x",
            "제목",
            "행정안전부",
            "2026-04-10T06:00:00",
            "central",
            "https://example.com/x",
            "hwpx",
        )
        conn.close()


def test_process_md_files_keeps_write_order() -> None:
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        data_root = root / "data"
        paths.ensure_dirs(data_root)
        db_path = root / "govpress.db"
        conn = sqlite3.connect(db_path)
        derive_hot._ensure_sqlite_schema(conn)

        md_paths: list[Path] = []
        for idx in range(3):
            md_path = data_root / "md" / "2026" / "04" / f"{idx}.md"
            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_path.write_text(
                frontmatter.prepend(
                    f"body {idx}\n",
                    {
                        "id": str(idx),
                        "title": f"제목 {idx}",
                        "department": "행정안전부",
                        "approve_date": "2026-04-10T06:00:00",
                        "entity_type": "central",
                        "original_url": f"https://example.com/{idx}",
                        "sha256": "abc",
                        "revision": 1,
                        "govpress_version": "0.1.12",
                        "govpress_commit": "abcdef123456",
                        "source_format": "hwpx",
                        "raw_path": f"data/raw/2026/04/{idx}.hwpx",
                    },
                ),
                encoding="utf-8",
            )
            md_paths.append(md_path)

        write_order: list[str] = []
        original_embed = derive_hot._embed_chunks
        original_upsert_qdrant = derive_hot._upsert_qdrant
        original_write_checkpoint = derive_hot._write_checkpoint
        try:
            def fake_embed(tei_url: str, chunks: list[derive_hot.Chunk]) -> tuple[list[list[float]], float]:
                if chunks[0].news_item_id == "0":
                    time.sleep(0.05)
                return [[0.0] * derive_hot.EMBED_DIM for _ in chunks], 0.01

            def fake_upsert_qdrant(qdrant_url: str, chunks: list[derive_hot.Chunk], vectors: list[list[float]]) -> None:
                write_order.append(chunks[0].news_item_id)

            derive_hot._embed_chunks = fake_embed
            derive_hot._upsert_qdrant = fake_upsert_qdrant
            derive_hot._write_checkpoint = lambda checkpoint_path, md_path: None

            stats = derive_hot.RunStats(md_files=len(md_paths))
            failures: list[dict[str, str]] = []
            derive_hot._process_md_files(
                md_files=md_paths,
                tei_url="http://example.com",
                qdrant_url="http://example.com",
                conn=conn,
                checkpoint=10,
                checkpoint_path=root / "checkpoint.json",
                stats=stats,
                failures=failures,
                enable_checkpoint_writes=True,
            )
        finally:
            derive_hot._embed_chunks = original_embed
            derive_hot._upsert_qdrant = original_upsert_qdrant
            derive_hot._write_checkpoint = original_write_checkpoint

        assert failures == []
        assert write_order == ["0", "1", "2"]
        conn.close()


def test_process_md_files_can_skip_checkpoint_writes() -> None:
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        data_root = root / "data"
        paths.ensure_dirs(data_root)
        db_path = root / "govpress.db"
        conn = sqlite3.connect(db_path)
        derive_hot._ensure_sqlite_schema(conn)

        md_path = data_root / "md" / "2026" / "04" / "x.md"
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(
            frontmatter.prepend(
                "body\n",
                {
                    "id": "x",
                    "title": "제목",
                    "department": "행정안전부",
                    "approve_date": "2026-04-10T06:00:00",
                    "entity_type": "central",
                    "original_url": "https://example.com/x",
                    "sha256": "abc",
                    "revision": 1,
                    "govpress_version": "0.1.12",
                    "govpress_commit": "abcdef123456",
                    "source_format": "hwpx",
                    "raw_path": "data/raw/2026/04/x.hwpx",
                },
            ),
            encoding="utf-8",
        )

        checkpoint_calls: list[str] = []
        original_embed = derive_hot._embed_chunks
        original_upsert_qdrant = derive_hot._upsert_qdrant
        original_write_checkpoint = derive_hot._write_checkpoint
        try:
            derive_hot._embed_chunks = lambda tei_url, chunks: (
                [[0.0] * derive_hot.EMBED_DIM for _ in chunks],
                0.01,
            )
            derive_hot._upsert_qdrant = lambda qdrant_url, chunks, vectors: None
            derive_hot._write_checkpoint = lambda checkpoint_path, md_path: checkpoint_calls.append(str(md_path))

            stats = derive_hot.RunStats(md_files=1)
            failures: list[dict[str, str]] = []
            derive_hot._process_md_files(
                md_files=[md_path],
                tei_url="http://example.com",
                qdrant_url="http://example.com",
                conn=conn,
                checkpoint=1,
                checkpoint_path=root / "checkpoint.json",
                stats=stats,
                failures=failures,
                enable_checkpoint_writes=False,
            )
        finally:
            derive_hot._embed_chunks = original_embed
            derive_hot._upsert_qdrant = original_upsert_qdrant
            derive_hot._write_checkpoint = original_write_checkpoint

        assert failures == []
        assert checkpoint_calls == []
        conn.close()
