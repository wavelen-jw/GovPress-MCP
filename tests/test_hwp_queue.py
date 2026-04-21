import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

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


def test_m4_existing_hwpx_creates_md_and_upgrades_checksum_format() -> None:
    with TemporaryDirectory() as tmp_dir:
        data_root = Path(tmp_dir) / "data"
        paths.ensure_dirs(data_root)
        store = checksums.open_store(data_root / "fetch-log" / "checksums.db")
        item = PolicyBriefingItem(
            news_item_id="m4-1",
            title="제목",
            department="행정안전부",
            approve_date="04/10/2026 06:00:00",
            original_url="https://www.korea.kr/example",
            attachments=(),
        )
        # existing hwp-only checksum row from M3
        store.put(
            news_item_id="m4-1",
            sha256="old-hwp-sha",
            revision=1,
            fetched_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            source_format="hwp",
        )
        raw_path = data_root / "raw" / "2026" / "04" / "m4-1.hwpx"
        paths.atomic_write_bytes(raw_path, b"PK\x03\x04m4-hwpx")
        entry = bulk_ingest.HwpQueueEntry(
            news_item_id="m4-1",
            approve_date=bulk_ingest._parse_iso_date("2026-04-10"),
            hwp_path="raw/2026/04/m4-1.hwp",
            reason="hwp_legacy",
        )

        with patch.object(bulk_ingest, "_convert_raw_to_md", lambda raw: "# converted"), patch.object(
            bulk_ingest,
            "_converter_metadata",
            lambda: ("0.1.11", "deadbeefcafe"),
        ):
            outcome = asyncio.run(
                bulk_ingest._process_hwp_queue_entry(
                    entry=entry,
                    item=item,
                    data_root=data_root,
                    checksum_store=store,
                    semaphore=asyncio.Semaphore(5),
                )
            )

        assert outcome.status == "success"
        md_path = data_root / "md" / "2026" / "04" / "m4-1.md"
        assert md_path.exists()
        parsed, body = __import__("govpress_mcp.frontmatter", fromlist=["parse"]).parse(md_path.read_text(encoding="utf-8"))
        assert parsed["source_format"] == "hwpx"
        assert parsed["raw_path"] == "data/raw/2026/04/m4-1.hwpx"
        assert body.strip() == "# converted"
        record = store.get("m4-1")
        assert record is not None
        assert record.source_format == "hwpx"


def test_m4_missing_hwpx_records_distribution_only_reason() -> None:
    with TemporaryDirectory() as tmp_dir:
        data_root = Path(tmp_dir) / "data"
        paths.ensure_dirs(data_root)
        store = checksums.open_store(data_root / "fetch-log" / "checksums.db")
        entry = bulk_ingest.HwpQueueEntry(
            news_item_id="m4-missing",
            approve_date=bulk_ingest._parse_iso_date("2026-04-10"),
            hwp_path="raw/2026/04/m4-missing.hwp",
            reason="hwp_legacy",
        )
        item = PolicyBriefingItem(
            news_item_id="m4-missing",
            title="제목",
            department="행정안전부",
            approve_date="04/10/2026 06:00:00",
            original_url="https://www.korea.kr/example",
            attachments=(),
        )

        outcome = asyncio.run(
            bulk_ingest._process_hwp_queue_entry(
                entry=entry,
                item=item,
                data_root=data_root,
                checksum_store=store,
                semaphore=asyncio.Semaphore(5),
            )
        )

        assert outcome.status == "hwp_distribution_only"
        rows = [
            json.loads(line)
            for line in (data_root / "fetch-log" / "failed.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        assert rows == [{"news_item_id": "m4-missing", "reason": "hwp_distribution_only"}]


def test_write_hwp_distribution_only_list_writes_reason_annotated_ids() -> None:
    with TemporaryDirectory() as tmp_dir:
        data_root = Path(tmp_dir) / "data"
        paths.ensure_dirs(data_root)
        existing_hwpx = data_root / "raw" / "2026" / "04" / "m4-present.hwpx"
        paths.atomic_write_bytes(existing_hwpx, b"PK\x03\x04present")
        entries = [
            bulk_ingest.HwpQueueEntry(
                news_item_id="m4-missing",
                approve_date=bulk_ingest._parse_iso_date("2026-04-10"),
                hwp_path="raw/2026/04/m4-missing.hwp",
                reason="hwp_legacy",
            ),
            bulk_ingest.HwpQueueEntry(
                news_item_id="m4-present",
                approve_date=bulk_ingest._parse_iso_date("2026-04-10"),
                hwp_path="raw/2026/04/m4-present.hwp",
                reason="hwp_legacy",
            ),
        ]

        bulk_ingest._write_hwp_distribution_only_list(data_root, entries)

        output = (data_root / "fetch-log" / "hwpx-missing-52.txt").read_text(encoding="utf-8")
        assert output == "m4-missing # reason: hwp_distribution_only\n"


def test_parse_args_supports_from_hwp_queue_milestone() -> None:
    args = SimpleNamespace(
        from_hwp_queue=Path("data/fetch-log/hwp-queue.jsonl"),
        date=None,
        start_date=None,
        end_date=None,
        date_range=None,
        limit=None,
    )
    assert bulk_ingest._current_milestone(args) == "M4"
