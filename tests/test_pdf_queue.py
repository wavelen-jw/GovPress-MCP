import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from govpress_mcp import bulk_ingest, checksums, paths
from govpress_mcp.vendored.policy_briefing import (
    DownloadedPolicyBriefingFile,
    PolicyBriefingAttachment,
    PolicyBriefingItem,
)


class FakePdfClient:
    def __init__(self, content: bytes) -> None:
        self._content = content

    def download_attachment(
        self,
        item: PolicyBriefingItem,
        attachment: PolicyBriefingAttachment,
    ) -> DownloadedPolicyBriefingFile:
        return DownloadedPolicyBriefingFile(item=item, attachment=attachment, content=self._content)


def test_no_primary_hwpx_with_pdf_is_downloaded_and_queued() -> None:
    with TemporaryDirectory() as tmp_dir:
        data_root = Path(tmp_dir) / "data"
        paths.ensure_dirs(data_root)
        store = checksums.open_store(data_root / "fetch-log" / "checksums.db")
        item = PolicyBriefingItem(
            news_item_id="news-queue-1",
            title="제목",
            department="행정안전부",
            approve_date="04/10/2026 06:00:00",
            original_url="https://www.korea.kr/example",
            attachments=(
                PolicyBriefingAttachment(file_name="main.pdf", file_url="https://example.com/main.pdf"),
            ),
        )

        outcome = asyncio.run(
            bulk_ingest._process_one(
                client=FakePdfClient(b"%PDF-1.7 sample"),
                item=item,
                data_root=data_root,
                checksum_store=store,
                semaphore=asyncio.Semaphore(5),
                dry_run=False,
            )
        )

        assert outcome.status == "pdf_collected"
        raw_path = data_root / "raw" / "2026" / "04" / "news-queue-1.pdf"
        assert raw_path.read_bytes() == b"%PDF-1.7 sample"
        queue_path = data_root / "fetch-log" / "pdf-queue.jsonl"
        rows = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines()]
        assert rows == [
            {
                "news_item_id": "news-queue-1",
                "approve_date": "2026-04-10",
                "reason": "no_primary_hwpx",
            }
        ]


def test_load_pdf_queue_includes_existing_raw_pdf_from_original_backup() -> None:
    with TemporaryDirectory() as tmp_dir:
        repo_root = Path(tmp_dir)
        data_root = repo_root / "data"
        paths.ensure_dirs(data_root)
        raw_path = data_root / "raw" / "2026" / "04" / "pdf-existing.pdf"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(b"%PDF-1.7 existing")

        queue_path = data_root / "fetch-log" / "pdf-queue.jsonl"
        queue_path.write_text(
            json.dumps({"news_item_id": "pdf-new", "approve_date": "2026-04-11", "reason": "no_primary_hwpx"}, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        backup_path = data_root / "fetch-log" / "pdf-queue.original-20260419-214848.jsonl"
        backup_path.write_text(
            json.dumps({"news_item_id": "pdf-existing", "approve_date": "2026-04-10", "reason": "no_primary_hwpx"}, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )

        entries = bulk_ingest._load_pdf_queue(queue_path, data_root)

        assert [(entry.news_item_id, entry.approve_date.isoformat()) for entry in entries] == [
            ("pdf-existing", "2026-04-10"),
            ("pdf-new", "2026-04-11"),
        ]


def test_process_pdf_queue_entry_existing_raw_creates_markdown() -> None:
    with TemporaryDirectory() as tmp_dir:
        data_root = Path(tmp_dir) / "data"
        paths.ensure_dirs(data_root)
        store = checksums.open_store(data_root / "fetch-log" / "checksums.db")

        item = PolicyBriefingItem(
            news_item_id="pdf-existing",
            title="PDF 제목",
            department="행정안전부",
            approve_date="04/10/2026 06:00:00",
            original_url="https://www.korea.kr/example",
            attachments=(PolicyBriefingAttachment(file_name="main.pdf", file_url="https://example.com/main.pdf"),),
        )
        raw_path = data_root / "raw" / "2026" / "04" / "pdf-existing.pdf"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(b"%PDF-1.7 existing")
        store.put(
            news_item_id="pdf-existing",
            sha256=bulk_ingest.hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            revision=1,
            fetched_at=bulk_ingest.datetime.now(bulk_ingest.UTC),
            source_format="pdf",
        )

        with patch("govpress_mcp.bulk_ingest.govpress_converter.convert_pdf", return_value="converted pdf body"), patch(
            "govpress_mcp.bulk_ingest._converter_metadata",
            return_value=("0.1.11", "deadbeefcafe"),
        ):
            outcome = asyncio.run(
                bulk_ingest._process_pdf_queue_entry(
                    client=FakePdfClient(b"%PDF-1.7 unused"),
                    entry=bulk_ingest.PdfQueueEntry(
                        news_item_id="pdf-existing",
                        approve_date=bulk_ingest._parse_iso_date("2026-04-10"),
                        reason="no_primary_hwpx",
                    ),
                    item=item,
                    data_root=data_root,
                    checksum_store=store,
                    semaphore=asyncio.Semaphore(5),
                )
            )

        assert outcome.status == "pdf_existing_success"
        md_path = data_root / "md" / "2026" / "04" / "pdf-existing.md"
        md_text = md_path.read_text(encoding="utf-8")
        assert "source_format: 'pdf'" in md_text
        assert "converted pdf body" in md_text


def test_process_pdf_queue_entry_downloads_and_converts_pdf() -> None:
    with TemporaryDirectory() as tmp_dir:
        data_root = Path(tmp_dir) / "data"
        paths.ensure_dirs(data_root)
        store = checksums.open_store(data_root / "fetch-log" / "checksums.db")
        item = PolicyBriefingItem(
            news_item_id="pdf-new",
            title="PDF 제목",
            department="행정안전부",
            approve_date="04/11/2026 06:00:00",
            original_url="https://www.korea.kr/example",
            attachments=(PolicyBriefingAttachment(file_name="main.pdf", file_url="https://example.com/main.pdf"),),
        )

        with patch("govpress_mcp.bulk_ingest.govpress_converter.convert_pdf", return_value="converted downloaded pdf"), patch(
            "govpress_mcp.bulk_ingest._converter_metadata",
            return_value=("0.1.11", "deadbeefcafe"),
        ):
            outcome = asyncio.run(
                bulk_ingest._process_pdf_queue_entry(
                    client=FakePdfClient(b"%PDF-1.7 downloaded"),
                    entry=bulk_ingest.PdfQueueEntry(
                        news_item_id="pdf-new",
                        approve_date=bulk_ingest._parse_iso_date("2026-04-11"),
                        reason="no_primary_hwpx",
                    ),
                    item=item,
                    data_root=data_root,
                    checksum_store=store,
                    semaphore=asyncio.Semaphore(5),
                )
            )

        assert outcome.status == "pdf_downloaded_success"
        raw_path = data_root / "raw" / "2026" / "04" / "pdf-new.pdf"
        md_path = data_root / "md" / "2026" / "04" / "pdf-new.md"
        assert raw_path.read_bytes() == b"%PDF-1.7 downloaded"
        assert "source_format: 'pdf'" in md_path.read_text(encoding="utf-8")
