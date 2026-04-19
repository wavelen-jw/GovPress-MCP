import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

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
