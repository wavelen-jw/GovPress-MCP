from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from govpress_mcp import checksums, frontmatter, paths, reconvert


def test_check_regression_detects_large_drop() -> None:
    old_body = "line\n" * 20 + "\n| a | b |\n| --- | --- |\n| 1 | 2 |\n"
    new_body = "short\n"
    guard = reconvert._check_regression(old_body, new_body)

    assert guard["ok"] is False
    assert guard["body_drop_ratio"] > 0.2


def test_reconvert_one_updates_markdown_and_checksum() -> None:
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        data_root = root / "data"
        paths.ensure_dirs(data_root)
        raw_path = data_root / "raw" / "2026" / "04" / "item-1.hwpx"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(b"PK\x03\x04dummy")

        md_path = data_root / "md" / "2026" / "04" / "item-1.md"
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(
            frontmatter.prepend(
                "old body\n",
                {
                    "id": "item-1",
                    "title": "기존 제목",
                    "department": "행정안전부",
                    "approve_date": "2026-04-10T06:00:00",
                    "entity_type": "central",
                    "original_url": "https://example.com/1",
                    "sha256": "old",
                    "revision": 1,
                    "govpress_version": "0.1.11",
                    "govpress_commit": "abcdef123456",
                    "source_format": "hwpx",
                    "raw_path": "data/raw/2026/04/item-1.hwpx",
                },
            ),
            encoding="utf-8",
        )

        store = checksums.open_store(data_root / "fetch-log" / "checksums.db")
        store.put(
            news_item_id="item-1",
            sha256="old",
            revision=1,
            fetched_at=datetime.now(timezone.utc),
            govpress_version="0.1.11",
            govpress_commit="abcdef123456",
            source_format="hwpx",
        )

        target = reconvert.ReconvertTarget(
            news_item_id="item-1",
            source_format="hwpx",
            raw_path=raw_path,
            md_path=md_path,
            target_date=date(2026, 4, 10),
            origin="failed",
            previous_frontmatter=frontmatter.parse(md_path.read_text(encoding="utf-8"))[0],
            previous_body=frontmatter.parse(md_path.read_text(encoding="utf-8"))[1],
        )
        item = SimpleNamespace(
            news_item_id="item-1",
            title="새 제목",
            department="행정안전부",
            approve_date="04/10/2026 06:00:00",
            original_url="https://example.com/1",
        )

        with patch.object(reconvert.bulk_ingest, "_convert_raw_to_md", return_value="new body\n"), patch.object(
            reconvert.bulk_ingest, "_converter_metadata", return_value=("0.2.0", "123456789abc")
        ):
            result = reconvert._reconvert_one(
                target=target,
                metadata=item,
                data_root=data_root,
                checksum_store=store,
                dry_run=False,
                show_diff=False,
            )
            store.commit()

        assert result.status == "success"
        updated_fm, updated_body = frontmatter.parse(md_path.read_text(encoding="utf-8"))
        assert updated_fm["govpress_version"] == "0.2.0"
        assert updated_fm["govpress_commit"] == "123456789abc"
        assert updated_fm["source_format"] == "hwpx"
        assert updated_body == "new body\n"
        record = store.get("item-1")
        assert record is not None
        assert record.govpress_version == "0.2.0"
        store.close()
