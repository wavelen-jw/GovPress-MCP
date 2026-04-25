from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from govpress_mcp import build_backfill_manifest


def _create_probe_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE probe_doc_meta (
            news_item_id TEXT PRIMARY KEY,
            target_date TEXT NOT NULL,
            title TEXT,
            department TEXT,
            approve_date TEXT,
            original_url TEXT,
            selected_format TEXT,
            data_contents_html TEXT,
            data_contents_text TEXT,
            data_contents_text_length INTEGER
        );
        CREATE TABLE probe_attachments (
            news_item_id TEXT NOT NULL,
            attachment_index INTEGER NOT NULL,
            file_name TEXT,
            file_url TEXT,
            extension TEXT,
            is_appendix INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (news_item_id, attachment_index)
        );
        CREATE TABLE probe_backfill_status (
            news_item_id TEXT PRIMARY KEY,
            target_date TEXT NOT NULL,
            title TEXT,
            department TEXT,
            approve_date TEXT,
            original_url TEXT,
            selected_format TEXT,
            has_md INTEGER NOT NULL,
            md_source_format TEXT,
            action TEXT NOT NULL,
            attachment_count INTEGER NOT NULL,
            data_contents_text_length INTEGER
        );
        """
    )
    docs = [
        ("api", "2024-01-01", "API", "부처", "01/01/2024 00:00:00", "https://korea.kr/a", "no_attachments", "<p>본문</p>", "본문", 2, "api_text_only", 0),
        ("hwp", "2018-01-01", "HWP", "부처", "01/01/2018 00:00:00", "https://korea.kr/h", "hwp", "", "", 0, "download_hwp", 2),
        ("pdf-missing", "2010-01-01", "PDF", "부처", "01/01/2010 00:00:00", "https://korea.kr/p", "pdf", "", "", 0, "download_pdf", 0),
    ]
    for row in docs:
        conn.execute(
            """
            INSERT INTO probe_doc_meta (
                news_item_id, target_date, title, department, approve_date, original_url,
                selected_format, data_contents_html, data_contents_text, data_contents_text_length
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            row[:10],
        )
        conn.execute(
            """
            INSERT INTO probe_backfill_status (
                news_item_id, target_date, title, department, approve_date, original_url,
                selected_format, has_md, md_source_format, action, attachment_count, data_contents_text_length
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, ?)
            """,
            row[:7] + (row[10], row[11], row[9]),
        )
    conn.executemany(
        """
        INSERT INTO probe_attachments (
            news_item_id, attachment_index, file_name, file_url, extension, is_appendix
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            ("hwp", 0, "appendix.hwp", "https://x/appendix", ".hwp", 1),
            ("hwp", 1, "main.hwp", "https://x/main", ".hwp", 0),
        ],
    )
    conn.commit()
    conn.close()


def test_build_manifest_selects_primary_attachment_and_review_fallback() -> None:
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        db_path = root / "probe.db"
        out_dir = root / "out"
        report = root / "report.md"
        _create_probe_db(db_path)

        args = build_backfill_manifest.build_parser().parse_args(
            [
                "--probe-db",
                str(db_path),
                "--out-dir",
                str(out_dir),
                "--report",
                str(report),
                "--overwrite",
            ]
        )
        build_backfill_manifest.run(args)

        api_rows = [json.loads(line) for line in (out_dir / "manifest-api-text.jsonl").read_text().splitlines()]
        hwp_rows = [json.loads(line) for line in (out_dir / "manifest-hwp-2018.jsonl").read_text().splitlines()]
        review_rows = [json.loads(line) for line in (out_dir / "manifest-review.jsonl").read_text().splitlines()]

        assert api_rows[0]["data_contents_text"] == "본문"
        assert hwp_rows[0]["attachment"]["file_name"] == "main.hwp"
        assert review_rows[0]["news_item_id"] == "pdf-missing"
        assert review_rows[0]["review_reason"] == "missing_attachment"
        assert "5년 단위 실행 배치" in report.read_text(encoding="utf-8")


def test_build_windows_goes_backwards_from_end_date() -> None:
    windows = build_backfill_manifest.build_windows(
        start=__import__("datetime").date(2014, 1, 1),
        end=__import__("datetime").date(2026, 4, 18),
        years=5,
    )

    assert windows[0].start.isoformat() == "2021-04-19"
    assert windows[0].end.isoformat() == "2026-04-18"
    assert windows[-1].start.isoformat() == "2014-01-01"
