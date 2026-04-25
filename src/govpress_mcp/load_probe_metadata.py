"""Load metadata-only probe JSONL into SQLite for planning expanded backfills."""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from govpress_mcp import paths


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS probe_doc_meta (
    news_item_id TEXT PRIMARY KEY,
    target_date TEXT NOT NULL,
    title TEXT,
    department TEXT,
    approve_date TEXT,
    original_url TEXT,
    selected_format TEXT,
    data_contents_html TEXT,
    data_contents_text TEXT,
    data_contents_text_length INTEGER,
    contents_status TEXT,
    modify_id TEXT,
    modify_date TEXT,
    approver_name TEXT,
    embargo_date TEXT,
    grouping_code TEXT,
    contents_type TEXT,
    api_fields_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS probe_attachments (
    news_item_id TEXT NOT NULL,
    attachment_index INTEGER NOT NULL,
    file_name TEXT,
    file_url TEXT,
    extension TEXT,
    is_appendix INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (news_item_id, attachment_index)
);

CREATE TABLE IF NOT EXISTS probe_failures (
    target_date TEXT PRIMARY KEY,
    error TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS probe_backfill_status (
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

CREATE TABLE IF NOT EXISTS probe_load_stats (
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_probe_doc_target_date ON probe_doc_meta(target_date);
CREATE INDEX IF NOT EXISTS idx_probe_doc_selected_format ON probe_doc_meta(selected_format);
CREATE INDEX IF NOT EXISTS idx_probe_doc_department ON probe_doc_meta(department);
CREATE INDEX IF NOT EXISTS idx_probe_attachments_ext ON probe_attachments(extension);
CREATE INDEX IF NOT EXISTS idx_probe_status_action ON probe_backfill_status(action);
CREATE INDEX IF NOT EXISTS idx_probe_status_date ON probe_backfill_status(target_date);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def reset_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DELETE FROM probe_backfill_status;
        DELETE FROM probe_attachments;
        DELETE FROM probe_doc_meta;
        DELETE FROM probe_failures;
        DELETE FROM probe_load_stats;
        """
    )
    conn.commit()


def load_items(
    conn: sqlite3.Connection,
    items_json: Path,
    *,
    checkpoint: int,
    sample: int | None = None,
) -> Counter[str]:
    stats: Counter[str] = Counter()
    doc_rows: list[tuple[Any, ...]] = []
    attachment_rows: list[tuple[Any, ...]] = []
    started = time.monotonic()
    with items_json.open("r", encoding="utf-8") as handle:
        for line in handle:
            if sample is not None and stats["items"] >= sample:
                break
            if not line.strip():
                continue
            payload = json.loads(line)
            if payload.get("event") != "item_metadata":
                continue
            api_fields = payload.get("api_fields") or {}
            if not isinstance(api_fields, dict):
                api_fields = {}
            news_item_id = str(payload["news_item_id"])
            doc_rows.append(
                (
                    news_item_id,
                    payload.get("target_date"),
                    payload.get("title"),
                    payload.get("department"),
                    payload.get("approve_date"),
                    payload.get("original_url"),
                    payload.get("selected_format"),
                    payload.get("data_contents_html"),
                    payload.get("data_contents_text"),
                    int(payload.get("data_contents_text_length") or 0),
                    api_fields.get("ContentsStatus"),
                    api_fields.get("ModifyId"),
                    api_fields.get("ModifyDate"),
                    api_fields.get("ApproverName"),
                    api_fields.get("EmbargoDate"),
                    api_fields.get("GroupingCode"),
                    api_fields.get("ContentsType"),
                    json.dumps(api_fields, ensure_ascii=False),
                )
            )
            for index, attachment in enumerate(payload.get("attachments") or []):
                attachment_rows.append(
                    (
                        news_item_id,
                        index,
                        attachment.get("file_name"),
                        attachment.get("file_url"),
                        attachment.get("extension"),
                        1 if attachment.get("is_appendix") else 0,
                    )
                )
            stats["items"] += 1
            stats[f"selected:{payload.get('selected_format')}"] += 1
            if len(doc_rows) >= checkpoint:
                _flush_item_rows(conn, doc_rows, attachment_rows)
                doc_rows.clear()
                attachment_rows.clear()
                elapsed = max(time.monotonic() - started, 0.001)
                print(
                    f"loaded items={stats['items']} rate={stats['items'] / elapsed:.1f}/s",
                    flush=True,
                )
    if doc_rows or attachment_rows:
        _flush_item_rows(conn, doc_rows, attachment_rows)
    return stats


def _flush_item_rows(
    conn: sqlite3.Connection,
    doc_rows: list[tuple[Any, ...]],
    attachment_rows: list[tuple[Any, ...]],
) -> None:
    with conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO probe_doc_meta (
                news_item_id, target_date, title, department, approve_date,
                original_url, selected_format, data_contents_html, data_contents_text,
                data_contents_text_length, contents_status, modify_id, modify_date,
                approver_name, embargo_date, grouping_code, contents_type, api_fields_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            doc_rows,
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO probe_attachments (
                news_item_id, attachment_index, file_name, file_url, extension, is_appendix
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            attachment_rows,
        )


def load_failures(conn: sqlite3.Connection, summary_json: Path) -> Counter[str]:
    stats: Counter[str] = Counter()
    latest_by_date: dict[str, str | None] = {}
    with summary_json.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if payload.get("event") == "date_summary" and payload.get("target_date"):
                latest_by_date[str(payload["target_date"])] = payload.get("error")
    rows = [(target_date, error) for target_date, error in latest_by_date.items() if error]
    with conn:
        conn.execute("DELETE FROM probe_failures")
        conn.executemany("INSERT OR REPLACE INTO probe_failures (target_date, error) VALUES (?, ?)", rows)
    stats["failed_dates"] = len(rows)
    return stats


def build_status(conn: sqlite3.Connection, govpress_db: Path) -> Counter[str]:
    govpress_resolved = govpress_db.expanduser().resolve()
    conn.execute("DETACH DATABASE govpress") if _has_attached(conn, "govpress") else None
    conn.execute("ATTACH DATABASE ? AS govpress", (str(govpress_resolved),))
    with conn:
        conn.execute("DELETE FROM probe_backfill_status")
        conn.execute(
            """
            INSERT OR REPLACE INTO probe_backfill_status (
                news_item_id, target_date, title, department, approve_date, original_url,
                selected_format, has_md, md_source_format, action, attachment_count,
                data_contents_text_length
            )
            SELECT
                p.news_item_id,
                p.target_date,
                p.title,
                p.department,
                p.approve_date,
                p.original_url,
                p.selected_format,
                CASE WHEN d.news_item_id IS NULL THEN 0 ELSE 1 END AS has_md,
                d.source_format AS md_source_format,
                CASE
                    WHEN d.news_item_id IS NOT NULL THEN 'already_collected'
                    WHEN p.selected_format = 'hwpx' THEN 'download_hwpx'
                    WHEN p.selected_format = 'hwp' THEN 'download_hwp'
                    WHEN p.selected_format = 'pdf' THEN 'download_pdf'
                    WHEN p.selected_format = 'no_attachments' THEN 'api_text_only'
                    ELSE 'skip_or_review'
                END AS action,
                COALESCE(a.attachment_count, 0),
                p.data_contents_text_length
            FROM probe_doc_meta p
            LEFT JOIN govpress.doc_meta d ON d.news_item_id = p.news_item_id
            LEFT JOIN (
                SELECT news_item_id, COUNT(*) AS attachment_count
                FROM probe_attachments
                GROUP BY news_item_id
            ) a ON a.news_item_id = p.news_item_id
            """
        )
    rows = conn.execute(
        "SELECT action, COUNT(*) FROM probe_backfill_status GROUP BY action ORDER BY action"
    ).fetchall()
    return Counter({str(action): int(count) for action, count in rows})


def _has_attached(conn: sqlite3.Connection, name: str) -> bool:
    return any(row[1] == name for row in conn.execute("PRAGMA database_list"))


def write_report(conn: sqlite3.Connection, report_path: Path, *, db_path: Path, items_json: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    total_docs = _scalar(conn, "SELECT COUNT(*) FROM probe_doc_meta")
    total_attachments = _scalar(conn, "SELECT COUNT(*) FROM probe_attachments")
    failed_dates = _scalar(conn, "SELECT COUNT(*) FROM probe_failures")
    input_rows = _scalar(conn, "SELECT value FROM probe_load_stats WHERE key = 'input_item_rows'")
    duplicate_rows = max(input_rows - total_docs, 0)
    lines = [
        "# Probe Metadata SQLite 적재 보고서",
        "",
        f"- 생성 시각: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 입력: `{items_json.as_posix()}`",
        f"- DB: `{db_path.as_posix()}`",
        f"- 입력 item row: {input_rows:,}건",
        f"- unique 문서ID: {total_docs:,}건",
        f"- 중복 item row: {duplicate_rows:,}건",
        f"- 첨부: {total_attachments:,}건",
        f"- 실패 날짜: {failed_dates:,}일",
        "",
        "## 수집 상태 대조",
        "",
        "| action | count |",
        "|---|---:|",
    ]
    for action, count in conn.execute(
        "SELECT action, COUNT(*) FROM probe_backfill_status GROUP BY action ORDER BY count(*) DESC"
    ):
        lines.append(f"| {action} | {count:,} |")
    lines.extend(["", "## 우선 포맷", "", "| selected_format | count |", "|---|---:|"])
    for selected_format, count in conn.execute(
        "SELECT selected_format, COUNT(*) FROM probe_doc_meta GROUP BY selected_format ORDER BY count(*) DESC"
    ):
        lines.append(f"| {selected_format} | {count:,} |")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _scalar(conn: sqlite3.Connection, sql: str) -> int:
    row = conn.execute(sql).fetchone()
    return int(row[0] if row else 0)


def run(args: argparse.Namespace) -> int:
    paths.assert_supported_data_root(args.db.parent)
    conn = connect(args.db)
    ensure_schema(conn)
    if args.rebuild:
        reset_tables(conn)
    item_stats = load_items(conn, args.items_json, checkpoint=args.checkpoint, sample=args.sample)
    failure_stats = load_failures(conn, args.summary_json)
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO probe_load_stats (key, value) VALUES ('input_item_rows', ?)",
            (int(item_stats["items"]),),
        )
    action_stats = build_status(conn, args.govpress_db)
    write_report(conn, args.report, db_path=args.db, items_json=args.items_json)
    conn.close()
    print(
        "probe metadata load complete "
        f"items={item_stats['items']} "
        f"failed_dates={failure_stats['failed_dates']} "
        f"actions={dict(action_stats)} "
        f"report={args.report}",
        flush=True,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load full probe metadata JSONL into SQLite.")
    parser.add_argument("--items-json", type=Path, required=True)
    parser.add_argument("--summary-json", type=Path, required=True)
    parser.add_argument("--db", type=Path, default=Path("data/probe-metadata.db"))
    parser.add_argument("--govpress-db", type=Path, default=Path("data/govpress.db"))
    parser.add_argument("--report", type=Path, default=Path("docs/probe-metadata-load-report.md"))
    parser.add_argument("--checkpoint", type=int, default=1000)
    parser.add_argument("--sample", type=int)
    parser.add_argument("--rebuild", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.checkpoint < 1:
        raise SystemExit("--checkpoint는 1 이상이어야 합니다.")
    if args.sample is not None and args.sample < 1:
        raise SystemExit("--sample은 1 이상이어야 합니다.")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
