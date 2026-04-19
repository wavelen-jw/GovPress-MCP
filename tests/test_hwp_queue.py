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


class FakeLegacyClient:
    def __init__(self, content: bytes) -> None:
        self._content = content

    def download_attachment(
        self,
        item: PolicyBriefingItem,
        attachment: PolicyBriefingAttachment,
    ) -> DownloadedPolicyBriefingFile:
        return DownloadedPolicyBriefingFile(
            item=item,
            attachment=attachment,
            content=self._content,
        )


def test_legacy_hwp_is_saved_and_queued() -> None:
    with TemporaryDirectory() as tmp_dir:
        data_root = Path(tmp_dir) / "data"
        paths.ensure_dirs(data_root)
        store = checksums.open_store(data_root / "fetch-log" / "checksums.db")
        item = PolicyBriefingItem(
            news_item_id="legacy-1",
            title="제목",
            department="행정안전부",
            approve_date="04/10/2026 06:00:00",
            original_url="https://www.korea.kr/example",
            attachments=(PolicyBriefingAttachment(file_name="main.hwpx", file_url="https://example.com/main.hwpx"),),
        )

        outcome = asyncio.run(
            bulk_ingest._process_one(
                client=FakeLegacyClient(b"\xd0\xcf\x11\xe0legacy-hwp"),
                item=item,
                data_root=data_root,
                checksum_store=store,
                semaphore=asyncio.Semaphore(5),
                dry_run=False,
            )
        )

        assert outcome.status == "hwp_legacy"
        raw_path = data_root / "raw" / "2026" / "04" / "legacy-1.hwp"
        assert raw_path.read_bytes() == b"\xd0\xcf\x11\xe0legacy-hwp"

        queue_path = data_root / "fetch-log" / "hwp-queue.jsonl"
        rows = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines()]
        assert rows == [
            {
                "news_item_id": "legacy-1",
                "approve_date": "2026-04-10",
                "reason": "hwp_legacy",
                "hwp_path": "raw/2026/04/legacy-1.hwp",
            }
        ]


def test_hwp_only_collects_hwp_attachment_without_primary_hwpx() -> None:
    with TemporaryDirectory() as tmp_dir:
        data_root = Path(tmp_dir) / "data"
        paths.ensure_dirs(data_root)
        store = checksums.open_store(data_root / "fetch-log" / "checksums.db")
        item = PolicyBriefingItem(
            news_item_id="legacy-2",
            title="제목",
            department="행정안전부",
            approve_date="04/10/2026 06:00:00",
            original_url="https://www.korea.kr/example",
            attachments=(
                PolicyBriefingAttachment(file_name="main.hwp", file_url="https://example.com/main.hwp"),
                PolicyBriefingAttachment(file_name="main.pdf", file_url="https://example.com/main.pdf"),
            ),
        )

        outcome = asyncio.run(
            bulk_ingest._process_one(
                client=FakeLegacyClient(b"\xd0\xcf\x11\xe0legacy-hwp"),
                item=item,
                data_root=data_root,
                checksum_store=store,
                semaphore=asyncio.Semaphore(5),
                dry_run=False,
            )
        )

        assert outcome.status == "hwp_attachment"
        raw_path = data_root / "raw" / "2026" / "04" / "legacy-2.hwp"
        assert raw_path.read_bytes() == b"\xd0\xcf\x11\xe0legacy-hwp"

        queue_path = data_root / "fetch-log" / "hwp-queue.jsonl"
        rows = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines()]
        assert rows == [
            {
                "news_item_id": "legacy-2",
                "approve_date": "2026-04-10",
                "reason": "no_primary_hwpx_hwp_attachment",
                "hwp_path": "raw/2026/04/legacy-2.hwp",
            }
        ]
