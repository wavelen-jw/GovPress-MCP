import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from govpress_mcp import bulk_ingest, checksums, paths
from govpress_mcp.vendored.policy_briefing import (
    DownloadedPolicyBriefingFile,
    PolicyBriefingAttachment,
    PolicyBriefingItem,
)


class FakeClient:
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


def test_idempotency_skip_same_sha() -> None:
    with TemporaryDirectory() as tmp_dir:
        data_root = Path(tmp_dir) / "data"
        paths.ensure_dirs(data_root)
        store = checksums.open_store(data_root / "fetch-log" / "checksums.db")
        item = PolicyBriefingItem(
            news_item_id="news-1",
            title="제목",
            department="행정안전부",
            approve_date="04/10/2026 06:00:00",
            original_url="https://www.korea.kr/example",
            attachments=(PolicyBriefingAttachment(file_name="main.hwpx", file_url="https://example.com/main.hwpx"),),
        )

        with patch.object(bulk_ingest, "_convert_raw_to_md", lambda raw_path: "# converted"), patch.object(
            bulk_ingest,
            "_converter_metadata",
            lambda: ("0.1.9", "85cb2e8f57ce"),
        ):
            first = asyncio.run(
                bulk_ingest._process_one(
                    client=FakeClient(b"PK\x03\x04same-bytes"),
                    item=item,
                    data_root=data_root,
                    checksum_store=store,
                    semaphore=asyncio.Semaphore(5),
                    dry_run=False,
                )
            )
            second = asyncio.run(
                bulk_ingest._process_one(
                    client=FakeClient(b"PK\x03\x04same-bytes"),
                    item=item,
                    data_root=data_root,
                    checksum_store=store,
                    semaphore=asyncio.Semaphore(5),
                    dry_run=False,
                )
            )

        assert first.status == "success"
        assert second.status == "skip_sha"
