from __future__ import annotations

import json
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from govpress_mcp import checksums, frontmatter, run_backfill_manifest


def test_api_text_manifest_writes_markdown_and_checksum() -> None:
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        data_root = root / "data"
        manifest = root / "manifest-api-text.jsonl"
        log_json = root / "log.jsonl"
        manifest.write_text(
            json.dumps(
                {
                    "news_item_id": "api-1",
                    "target_date": "2026-04-17",
                    "approve_date": "04/17/2026 09:00:00",
                    "title": "제목",
                    "department": "행정안전부",
                    "original_url": "https://www.korea.kr/briefing/pressReleaseView.do?newsId=api-1",
                    "selected_format": "no_attachments",
                    "action": "api_text_only",
                    "data_contents_html": "<p>본문</p>",
                    "data_contents_text": "본문",
                    "data_contents_text_length": 2,
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        args = run_backfill_manifest.build_parser().parse_args(
            [
                "--data-root",
                str(data_root),
                "--manifest",
                str(manifest),
                "--log-json",
                str(log_json),
            ]
        )
        result = run_backfill_manifest.run(args)

        assert result == 0
        md_path = data_root / "md" / "2026" / "04" / "api-1.md"
        fm, body = frontmatter.parse(md_path.read_text(encoding="utf-8"))
        assert fm["source_format"] == "api_text"
        assert fm["id"] == "api-1"
        assert "본문" in body


def test_dry_run_does_not_write_markdown() -> None:
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        data_root = root / "data"
        manifest = root / "manifest-api-text.jsonl"
        manifest.write_text(
            json.dumps(
                {
                    "news_item_id": "api-2",
                    "target_date": "2026-04-17",
                    "approve_date": "04/17/2026 09:00:00",
                    "title": "제목",
                    "department": "행정안전부",
                    "original_url": "https://www.korea.kr/briefing/pressReleaseView.do?newsId=api-2",
                    "selected_format": "no_attachments",
                    "action": "api_text_only",
                    "data_contents_html": "<p>본문</p>",
                    "data_contents_text": "본문",
                    "data_contents_text_length": 2,
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        args = run_backfill_manifest.build_parser().parse_args(
            [
                "--data-root",
                str(data_root),
                "--manifest",
                str(manifest),
                "--log-json",
                str(root / "log.jsonl"),
                "--dry-run",
            ]
        )

        run_backfill_manifest.run(args)

        assert not (data_root / "md").exists()


def test_hwp_skip_sha_still_queues_existing_raw() -> None:
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        data_root = root / "data"
        raw_path = data_root / "raw" / "2026" / "04" / "hwp-1.hwp"
        raw_path.parent.mkdir(parents=True)
        content = b"hwp bytes"
        raw_path.write_bytes(content)
        checksum_store = checksums.open_store(data_root / "fetch-log" / "checksums.db")
        checksum_store.put(
            news_item_id="hwp-1",
            sha256=hashlib.sha256(content).hexdigest(),
            revision=1,
            fetched_at=datetime.now(UTC),
            source_format="hwp",
        )
        original_download = run_backfill_manifest.download_bytes
        original_sleep = run_backfill_manifest.ratelimit_sync_sleep
        run_backfill_manifest.download_bytes = lambda _url, _referer: content
        run_backfill_manifest.ratelimit_sync_sleep = lambda: None
        try:
            status = run_backfill_manifest.process_download(
                {
                    "news_item_id": "hwp-1",
                    "target_date": "2026-04-17",
                    "approve_date": "04/17/2026 09:00:00",
                    "title": "제목",
                    "department": "행정안전부",
                    "original_url": "https://www.korea.kr/briefing/pressReleaseView.do?newsId=hwp-1",
                    "action": "download_hwp",
                    "attachment": {"file_url": "https://example.invalid/file.hwp"},
                },
                data_root=data_root,
                checksum_store=checksum_store,
                dry_run=False,
                hwp_queue=data_root / "fetch-log" / "hwp-queue.jsonl",
            )
        finally:
            run_backfill_manifest.download_bytes = original_download
            run_backfill_manifest.ratelimit_sync_sleep = original_sleep
        checksum_store.close()

        queue_rows = [
            json.loads(line)
            for line in (data_root / "fetch-log" / "hwp-queue.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        assert status == "skip_sha"
        assert queue_rows == [
            {
                "news_item_id": "hwp-1",
                "approve_date": "2026-04-17",
                "reason": "expanded_backfill_hwp_existing_raw",
                "hwp_path": "raw/2026/04/hwp-1.hwp",
            }
        ]
