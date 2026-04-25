from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from govpress_mcp import probe_backfill
from govpress_mcp.vendored.policy_briefing import PolicyBriefingAttachment, PolicyBriefingItem


def _item(news_item_id: str, attachments: tuple[PolicyBriefingAttachment, ...]) -> PolicyBriefingItem:
    return PolicyBriefingItem(
        news_item_id=news_item_id,
        title="제목",
        department="부처",
        approve_date="04/10/2026 06:00:00",
        original_url="https://www.korea.kr/example",
        attachments=attachments,
        data_contents="<p>본문 &amp; 내용</p><br>",
        api_fields={"ContentsStatus": "U", "GroupingCode": "brief"},
    )


def _attachment(name: str) -> PolicyBriefingAttachment:
    return PolicyBriefingAttachment(file_name=name, file_url=f"https://www.korea.kr/{name}")


def test_summarize_items_uses_hwpx_hwp_pdf_priority() -> None:
    summary = probe_backfill.summarize_items(
        date(2020, 1, 1),
        [
            _item("1", (_attachment("main.hwpx"), _attachment("main.hwp"), _attachment("main.pdf"))),
            _item("2", (_attachment("main.hwp"), _attachment("main.pdf"))),
            _item("3", (_attachment("main.pdf"),)),
            _item("4", (_attachment("main.odt"),)),
            _item("5", ()),
            _item("6", (_attachment("main.xls"),)),
        ],
    )

    assert summary.item_count == 6
    assert summary.extension_counts[".hwpx"] == 1
    assert summary.extension_counts[".hwp"] == 2
    assert summary.extension_counts[".pdf"] == 3
    assert summary.extension_counts[".odt"] == 1
    assert summary.extension_counts["none"] == 1
    assert summary.extension_counts["other"] == 1
    assert summary.selected_format_counts["hwpx"] == 1
    assert summary.selected_format_counts["hwp"] == 1
    assert summary.selected_format_counts["pdf"] == 1
    assert summary.selected_format_counts["odt_only"] == 1
    assert summary.selected_format_counts["no_attachments"] == 1
    assert summary.selected_format_counts["other"] == 1


def test_load_completed_dates_reads_date_summary_events_only() -> None:
    with TemporaryDirectory() as tmp_dir:
        log_path = Path(tmp_dir) / "probe.jsonl"
        log_path.write_text(
            "\n".join(
                [
                    json.dumps({"event": "date_summary", "target_date": "2020-01-01"}),
                    json.dumps({"event": "other", "target_date": "2020-01-02"}),
                    "not-json",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        assert probe_backfill.load_completed_dates(log_path) == {"2020-01-01"}


def test_item_metadata_rows_preserve_attachment_details() -> None:
    rows = probe_backfill.item_metadata_rows(
        date(2020, 1, 1),
        [_item("1", (_attachment("main.hwp"), _attachment("appendix.pdf")))],
    )

    assert rows == [
        {
            "event": "item_metadata",
            "target_date": "2020-01-01",
            "news_item_id": "1",
            "title": "제목",
            "department": "부처",
            "approve_date": "04/10/2026 06:00:00",
            "original_url": "https://www.korea.kr/example",
            "data_contents_html": "<p>본문 &amp; 내용</p><br>",
            "data_contents_text": "본문 & 내용",
            "data_contents_text_length": 7,
            "api_fields": {"ContentsStatus": "U", "GroupingCode": "brief"},
            "selected_format": "hwp",
            "attachments": [
                {
                    "file_name": "main.hwp",
                    "file_url": "https://www.korea.kr/main.hwp",
                    "extension": ".hwp",
                    "is_appendix": False,
                },
                {
                    "file_name": "appendix.pdf",
                    "file_url": "https://www.korea.kr/appendix.pdf",
                    "extension": ".pdf",
                    "is_appendix": False,
                },
            ],
        }
    ]


def test_aggregate_log_deduplicates_dates_and_writes_report() -> None:
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        log_path = root / "probe.jsonl"
        report_path = root / "report.md"
        rows = [
            probe_backfill.DateSummary(
                target_date="2020-01-01",
                item_count=2,
                extension_counts={".hwpx": 1, ".pdf": 1},
                selected_format_counts={"hwpx": 1, "pdf": 1},
                duration_seconds=1.0,
            ).to_json(),
            probe_backfill.DateSummary(
                target_date="2020-01-01",
                item_count=999,
                extension_counts={".hwp": 999},
                selected_format_counts={"hwp": 999},
            ).to_json(),
            probe_backfill.DateSummary(
                target_date="2020-01-02",
                item_count=0,
                error="RuntimeError: fail",
            ).to_json(),
        ]
        log_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")

        aggregate = probe_backfill.aggregate_log(log_path, date(2020, 1, 1), date(2020, 1, 2))
        probe_backfill.write_report(report_path, aggregate, log_path=log_path)

        assert aggregate.completed_days == 2
        assert aggregate.successful_days == 1
        assert aggregate.failed_days == 1
        assert aggregate.total_items == 999
        assert aggregate.selected_format_counts["hwp"] == 999
        text = report_path.read_text(encoding="utf-8")
        assert "전체 문서: 999건" in text
        assert "2020-01-02: RuntimeError: fail" in text
