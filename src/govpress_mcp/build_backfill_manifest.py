"""Build execution manifests from probe metadata without downloading files."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from govpress_mcp import paths


ACTION_TO_FILE = {
    "api_text_only": "manifest-api-text.jsonl",
    "download_hwpx": "manifest-hwpx.jsonl",
    "download_pdf": "manifest-pdf.jsonl",
    "skip_or_review": "manifest-review.jsonl",
}
DOWNLOAD_ACTIONS = {"download_hwpx", "download_hwp", "download_pdf"}
EXTENSION_BY_ACTION = {
    "download_hwpx": ".hwpx",
    "download_hwp": ".hwp",
    "download_pdf": ".pdf",
}


@dataclass(frozen=True)
class BatchWindow:
    label: str
    start: date
    end: date


def connect(probe_db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(probe_db)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_out_dir(out_dir: Path) -> None:
    paths.assert_supported_data_root(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)


def build_windows(*, start: date, end: date, years: int) -> list[BatchWindow]:
    windows: list[BatchWindow] = []
    current_end = end
    index = 1
    while current_end >= start:
        current_start = _add_years(current_end + timedelta(days=1), -years)
        if current_start < start:
            current_start = start
        windows.append(
            BatchWindow(
                label=f"batch-{index:02d}-{current_start.isoformat()}..{current_end.isoformat()}",
                start=current_start,
                end=current_end,
            )
        )
        current_end = current_start - timedelta(days=1)
        index += 1
    return windows


def _add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


def selected_attachment(conn: sqlite3.Connection, news_item_id: str, action: str) -> dict[str, Any] | None:
    extension = EXTENSION_BY_ACTION.get(action)
    if extension is None:
        return None
    row = conn.execute(
        """
        SELECT file_name, file_url, extension, is_appendix
        FROM probe_attachments
        WHERE news_item_id = ? AND extension = ?
        ORDER BY is_appendix ASC, attachment_index ASC
        LIMIT 1
        """,
        (news_item_id, extension),
    ).fetchone()
    if row is None:
        return None
    return {
        "file_name": row["file_name"],
        "file_url": row["file_url"],
        "extension": row["extension"],
        "is_appendix": bool(row["is_appendix"]),
    }


def iter_status_rows(
    conn: sqlite3.Connection,
    *,
    action: str,
    year: int | None = None,
    sample: int | None = None,
) -> Iterable[sqlite3.Row]:
    params: list[Any] = [action]
    where = ["action = ?"]
    if year is not None:
        where.append("substr(target_date, 1, 4) = ?")
        params.append(str(year))
    sql = f"""
        SELECT
            s.news_item_id, s.target_date, s.title, s.department, s.approve_date,
            s.original_url, s.selected_format, s.action, s.data_contents_text_length,
            p.data_contents_html, p.data_contents_text
        FROM probe_backfill_status s
        JOIN probe_doc_meta p ON p.news_item_id = s.news_item_id
        WHERE {' AND '.join(where)}
        ORDER BY s.target_date DESC, s.news_item_id
    """
    if sample is not None:
        sql += " LIMIT ?"
        params.append(sample)
    yield from conn.execute(sql, params)


def row_payload(conn: sqlite3.Connection, row: sqlite3.Row) -> tuple[dict[str, Any], str | None]:
    payload: dict[str, Any] = {
        "news_item_id": row["news_item_id"],
        "target_date": row["target_date"],
        "approve_date": row["approve_date"],
        "title": row["title"],
        "department": row["department"],
        "original_url": row["original_url"],
        "selected_format": row["selected_format"],
        "action": row["action"],
    }
    action = row["action"]
    if action == "api_text_only":
        payload.update(
            {
                "data_contents_html": row["data_contents_html"],
                "data_contents_text": row["data_contents_text"],
                "data_contents_text_length": row["data_contents_text_length"],
            }
        )
        return payload, None
    if action in DOWNLOAD_ACTIONS:
        attachment = selected_attachment(conn, row["news_item_id"], action)
        if attachment is None or not attachment.get("file_url"):
            payload["missing_attachment_for_action"] = action
            return payload, "missing_attachment"
        payload["attachment"] = attachment
        return payload, None
    return payload, None


def manifest_path(out_dir: Path, action: str, *, target_date: str | None = None) -> Path:
    if action == "download_hwp":
        year = (target_date or "unknown")[:4]
        return out_dir / f"manifest-hwp-{year}.jsonl"
    return out_dir / ACTION_TO_FILE[action]


def build_manifests(
    conn: sqlite3.Connection,
    *,
    out_dir: Path,
    actions: set[str],
    year: int | None,
    sample: int | None,
    overwrite: bool,
) -> dict[str, Counter[str]]:
    ensure_out_dir(out_dir)
    handles: dict[Path, Any] = {}
    stats: dict[str, Counter[str]] = defaultdict(Counter)
    try:
        for action in sorted(actions):
            for row in iter_status_rows(conn, action=action, year=year, sample=sample):
                payload, issue = row_payload(conn, row)
                output_action = action
                if issue:
                    output_action = "skip_or_review"
                    payload["action"] = "skip_or_review"
                    payload["review_reason"] = issue
                path = manifest_path(out_dir, output_action, target_date=payload["target_date"])
                if path not in handles:
                    if path.exists() and not overwrite:
                        raise SystemExit(f"manifest가 이미 존재합니다. --overwrite 필요: {path}")
                    handles[path] = path.open("w", encoding="utf-8", newline="")
                handles[path].write(json.dumps(payload, ensure_ascii=False) + "\n")
                stats[output_action]["rows"] += 1
                stats[output_action][f"year:{payload['target_date'][:4]}"] += 1
                if issue:
                    stats[output_action][f"issue:{issue}"] += 1
    finally:
        for handle in handles.values():
            handle.close()
    return stats


def db_action_counts(conn: sqlite3.Connection) -> Counter[str]:
    return Counter(
        {
            str(action): int(count)
            for action, count in conn.execute(
                "SELECT action, COUNT(*) FROM probe_backfill_status GROUP BY action"
            )
        }
    )


def batch_counts(conn: sqlite3.Connection, windows: list[BatchWindow]) -> dict[str, Counter[str]]:
    result: dict[str, Counter[str]] = {}
    for window in windows:
        counter: Counter[str] = Counter()
        for action, count in conn.execute(
            """
            SELECT action, COUNT(*)
            FROM probe_backfill_status
            WHERE target_date BETWEEN ? AND ?
              AND action != 'already_collected'
            GROUP BY action
            """,
            (window.start.isoformat(), window.end.isoformat()),
        ):
            counter[str(action)] = int(count)
        result[window.label] = counter
    return result


def write_report(
    conn: sqlite3.Connection,
    report: Path,
    *,
    out_dir: Path,
    manifest_stats: dict[str, Counter[str]],
    windows: list[BatchWindow],
) -> None:
    report.parent.mkdir(parents=True, exist_ok=True)
    action_counts = db_action_counts(conn)
    batches = batch_counts(conn, windows)
    lines = [
        "# 확장 백필 Manifest 생성 보고서",
        "",
        f"- 생성 시각: {datetime.now().isoformat(timespec='seconds')}",
        f"- manifest 디렉터리: `{out_dir.as_posix()}`",
        "- 실제 다운로드/변환: 미실행",
        "- 실행 방향: 현재 기준일에서 5년씩 과거로 진행",
        "",
        "## DB 기준 action 분포",
        "",
        "| action | count |",
        "|---|---:|",
    ]
    for action, count in action_counts.most_common():
        lines.append(f"| {action} | {count:,} |")

    lines.extend(["", "## 생성된 manifest", "", "| manifest action | rows | issues |", "|---|---:|---:|"])
    for action in sorted(manifest_stats):
        rows = manifest_stats[action]["rows"]
        issues = sum(value for key, value in manifest_stats[action].items() if key.startswith("issue:"))
        lines.append(f"| {action} | {rows:,} | {issues:,} |")

    lines.extend(["", "## 5년 단위 실행 배치", "", "| 순서 | 기간 | 전체 후보 | api_text | hwpx | pdf | hwp | review |", "|---:|---|---:|---:|---:|---:|---:|---:|"])
    for index, window in enumerate(windows, start=1):
        counts = batches[window.label]
        total = sum(counts.values())
        lines.append(
            "| {index} | {start}..{end} | {total:,} | {api:,} | {hwpx:,} | {pdf:,} | {hwp:,} | {review:,} |".format(
                index=index,
                start=window.start.isoformat(),
                end=window.end.isoformat(),
                total=total,
                api=counts.get("api_text_only", 0),
                hwpx=counts.get("download_hwpx", 0),
                pdf=counts.get("download_pdf", 0),
                hwp=counts.get("download_hwp", 0),
                review=counts.get("skip_or_review", 0),
            )
        )

    lines.extend(
        [
            "",
            "## 권장 실행 순서",
            "",
            "1. 각 5년 배치 안에서 `api_text_only`를 먼저 MD 생성한다.",
            "2. 같은 배치의 `download_hwpx`를 처리한다.",
            "3. 같은 배치의 `download_pdf`를 처리한다.",
            "4. 같은 배치의 `download_hwp`는 서버H COM 변환 용량에 맞춰 연도별로 처리한다.",
            "5. `skip_or_review`는 변환 작업과 분리해 수동 분류한다.",
            "",
        ]
    )
    report.write_text("\n".join(lines), encoding="utf-8")


def parse_actions(text: str) -> set[str]:
    if text == "all":
        return {"api_text_only", "download_hwpx", "download_pdf", "download_hwp", "skip_or_review"}
    mapping = {"review": "skip_or_review"}
    actions = {mapping.get(part.strip(), part.strip()) for part in text.split(",") if part.strip()}
    valid = {"api_text_only", "download_hwpx", "download_pdf", "download_hwp", "skip_or_review"}
    unknown = actions - valid
    if unknown:
        raise SystemExit(f"알 수 없는 action: {', '.join(sorted(unknown))}")
    return actions


def run(args: argparse.Namespace) -> int:
    conn = connect(args.probe_db)
    start = datetime.strptime(args.range_start, "%Y-%m-%d").date()
    end = datetime.strptime(args.range_end, "%Y-%m-%d").date()
    windows = build_windows(start=start, end=end, years=args.batch_years)
    stats = build_manifests(
        conn,
        out_dir=args.out_dir,
        actions=parse_actions(args.action),
        year=args.year,
        sample=args.sample,
        overwrite=args.overwrite,
    )
    write_report(conn, args.report, out_dir=args.out_dir, manifest_stats=stats, windows=windows)
    conn.close()
    print(
        "manifest build complete "
        f"actions={sorted(stats)} "
        f"report={args.report}",
        flush=True,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build expanded backfill manifests from probe metadata.")
    parser.add_argument("--probe-db", type=Path, default=Path("data/probe-metadata.db"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/fetch-log"))
    parser.add_argument("--report", type=Path, default=Path("docs/backfill-manifest-report.md"))
    parser.add_argument("--action", default="all")
    parser.add_argument("--year", type=int)
    parser.add_argument("--sample", type=int)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--range-start", default="1999-02-18")
    parser.add_argument("--range-end", default="2026-04-18")
    parser.add_argument("--batch-years", type=int, default=5)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.sample is not None and args.sample < 1:
        raise SystemExit("--sample은 1 이상이어야 합니다.")
    if args.batch_years < 1:
        raise SystemExit("--batch-years는 1 이상이어야 합니다.")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
