from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from govpress_mcp import load_probe_metadata


def test_load_probe_metadata_and_build_status() -> None:
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        items_json = root / "items.jsonl"
        summary_json = root / "summary.jsonl"
        probe_db = root / "probe.db"
        govpress_db = root / "govpress.db"
        report = root / "report.md"

        items = [
            {
                "event": "item_metadata",
                "target_date": "2020-01-01",
                "news_item_id": "already",
                "title": "기존",
                "department": "부처",
                "approve_date": "01/01/2020 00:00:00",
                "original_url": "https://www.korea.kr/a",
                "selected_format": "hwpx",
                "data_contents_html": "<p>본문</p>",
                "data_contents_text": "본문",
                "data_contents_text_length": 2,
                "api_fields": {"ContentsStatus": "U", "ContentsType": "H"},
                "attachments": [{"file_name": "a.hwpx", "file_url": "https://x/a", "extension": ".hwpx"}],
            },
            {
                "event": "item_metadata",
                "target_date": "2020-01-02",
                "news_item_id": "missing-hwp",
                "title": "누락",
                "department": "부처",
                "approve_date": "01/02/2020 00:00:00",
                "original_url": "https://www.korea.kr/b",
                "selected_format": "hwp",
                "data_contents_html": "",
                "data_contents_text": "",
                "data_contents_text_length": 0,
                "api_fields": {},
                "attachments": [{"file_name": "b.hwp", "file_url": "https://x/b", "extension": ".hwp"}],
            },
        ]
        items_json.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in items), encoding="utf-8")
        summary_json.write_text(
            "\n".join(
                [
                    json.dumps({"event": "date_summary", "target_date": "2020-01-01", "error": None}),
                    json.dumps({"event": "date_summary", "target_date": "2020-01-03", "error": "ParseError"}),
                ]
            ),
            encoding="utf-8",
        )

        gov_conn = sqlite3.connect(govpress_db)
        gov_conn.execute(
            """
            CREATE TABLE doc_meta (
                news_item_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                department TEXT,
                approve_date TEXT,
                entity_type TEXT,
                source_url TEXT,
                source_format TEXT
            )
            """
        )
        gov_conn.execute(
            "INSERT INTO doc_meta (news_item_id, title, source_format) VALUES ('already', '기존', 'hwpx')"
        )
        gov_conn.commit()
        gov_conn.close()

        args = load_probe_metadata.build_parser().parse_args(
            [
                "--items-json",
                str(items_json),
                "--summary-json",
                str(summary_json),
                "--db",
                str(probe_db),
                "--govpress-db",
                str(govpress_db),
                "--report",
                str(report),
                "--rebuild",
            ]
        )
        load_probe_metadata.run(args)

        conn = sqlite3.connect(probe_db)
        assert conn.execute("SELECT COUNT(*) FROM probe_doc_meta").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM probe_attachments").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM probe_failures").fetchone()[0] == 1
        actions = dict(conn.execute("SELECT action, COUNT(*) FROM probe_backfill_status GROUP BY action"))
        assert actions == {"already_collected": 1, "download_hwp": 1}
        conn.close()
        assert "Probe Metadata SQLite 적재 보고서" in report.read_text(encoding="utf-8")
