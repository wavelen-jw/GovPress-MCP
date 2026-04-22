from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from govpress_mcp import bulk_ingest, checksums, entity_classify, frontmatter, paths
from govpress_mcp.vendored.policy_briefing import PolicyBriefingClient

UTC = timezone.utc
DEFAULT_CHECKPOINT = 50
FAILED_LOGS = (
    "backfill.jsonl",
    "unified-collect.jsonl",
    "unified-retry.jsonl",
    "m4-reprocess.jsonl",
    "m4-retry-4dates.jsonl",
    "m5-reprocess.jsonl",
    "m5-retry-4dates.jsonl",
)
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class ReconvertTarget:
    news_item_id: str
    source_format: str
    raw_path: Path
    md_path: Path
    target_date: date | None
    origin: str
    failure_reason: str | None = None
    previous_frontmatter: dict[str, str] | None = None
    previous_body: str | None = None


@dataclass
class ReconvertResult:
    news_item_id: str
    source_format: str
    status: str
    duration_seconds: float = 0.0
    note: str | None = None
    body_drop_ratio: float | None = None
    table_drop_ratio: float | None = None


@dataclass
class RunStats:
    total: int = 0
    successful: int = 0
    skipped_regression: int = 0
    skipped_metadata_missing: int = 0
    skipped_raw_missing: int = 0
    conversion_failed: int = 0
    dry_run_preview: int = 0
    durations: list[float] | None = None

    def __post_init__(self) -> None:
        if self.durations is None:
            self.durations = []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reconvert historical conversion_failed items.")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--target-version")
    parser.add_argument("--source-format", choices=("hwpx", "pdf", "all"), default="all")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sample", type=int)
    parser.add_argument("--diff", action="store_true")
    parser.add_argument("--checkpoint", type=int, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--log-json", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.diff and not args.sample:
        raise SystemExit("--diff 사용 시 --sample 이 필요합니다.")
    if args.checkpoint <= 0:
        raise SystemExit("--checkpoint 는 1 이상이어야 합니다.")

    data_root = _canonicalize_data_root(args.data_root)
    paths.ensure_dirs(data_root)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = args.log_json or data_root / "fetch-log" / f"reconvert-{timestamp}.jsonl"
    reconvert_failed_path = data_root / "fetch-log" / "reconvert-failed.jsonl"

    targets = _load_targets(
        data_root=data_root,
        target_version=args.target_version,
        source_format=args.source_format,
    )
    if args.sample is not None:
        targets = targets[: args.sample]

    metadata_map = _load_metadata_for_targets(targets)
    store = checksums.open_store(data_root / "fetch-log" / "checksums.db")
    stats = RunStats(total=len(targets))
    consecutive_regression_skips = 0
    started_at = datetime.now(UTC)

    try:
        for index, target in enumerate(targets, start=1):
            result = _reconvert_one(
                target=target,
                metadata=metadata_map.get(target.news_item_id),
                data_root=data_root,
                checksum_store=store,
                dry_run=args.dry_run,
                show_diff=args.diff,
            )
            _append_jsonl(
                log_path,
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "news_item_id": target.news_item_id,
                    "target_date": target.target_date.isoformat() if target.target_date else None,
                    "source_format": target.source_format,
                    "status": result.status,
                    "duration_seconds": round(result.duration_seconds, 6),
                    "note": result.note,
                    "body_drop_ratio": result.body_drop_ratio,
                    "table_drop_ratio": result.table_drop_ratio,
                },
            )
            _update_stats(stats, result)

            if result.status == "skip_regression_guard":
                consecutive_regression_skips += 1
                if consecutive_regression_skips >= 5:
                    raise SystemExit(
                        "EMERGENCY STOP: reconvert regression guard triggered 5 consecutive items."
                    )
            else:
                consecutive_regression_skips = 0

            if result.status in {"conversion_failed", "raw_missing", "item_metadata_missing"}:
                _append_jsonl(
                    reconvert_failed_path,
                    {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "news_item_id": target.news_item_id,
                        "target_date": target.target_date.isoformat() if target.target_date else None,
                        "source_format": target.source_format,
                        "status": result.status,
                        "reason": result.note,
                    },
                )

            if not args.dry_run and result.status == "success" and index % args.checkpoint == 0:
                store.commit()

        if not args.dry_run:
            store.commit()
    finally:
        store.close()

    finished_at = datetime.now(UTC)
    _write_report(
        data_root.parent / "docs" / "reconvert-report.md",
        stats=stats,
        started_at=started_at,
        finished_at=finished_at,
        source_format=args.source_format,
        dry_run=args.dry_run,
        sample=args.sample,
        log_path=log_path,
    )
    return 0


def _canonicalize_data_root(data_root: Path) -> Path:
    resolved = data_root.expanduser().resolve()
    repo_data = (Path.cwd() / "data").resolve()
    if resolved != repo_data:
        return repo_data
    return resolved


def _load_targets(*, data_root: Path, target_version: str | None, source_format: str) -> list[ReconvertTarget]:
    targets: dict[str, ReconvertTarget] = {}
    targets.update(_load_failed_targets(data_root=data_root, source_format=source_format))
    if target_version is not None:
        for target in _load_version_targets(data_root=data_root, target_version=target_version, source_format=source_format):
            targets.setdefault(target.news_item_id, target)
    return sorted(targets.values(), key=lambda t: ((t.target_date or date.min), t.news_item_id))


def _load_failed_targets(*, data_root: Path, source_format: str) -> dict[str, ReconvertTarget]:
    target_dates = _load_conversion_failed_dates(data_root / "fetch-log")
    reasons = _load_failed_reasons(data_root / "fetch-log" / "failed.jsonl")
    targets: dict[str, ReconvertTarget] = {}

    for news_item_id, target_date in target_dates.items():
        raw_path, inferred_format = _locate_failed_raw(data_root, news_item_id, target_date)
        if source_format != "all" and inferred_format != source_format:
            continue
        md_path = paths.md_path(data_root, news_item_id, target_date.strftime("%m/%d/%Y 00:00:00"))
        previous_frontmatter = None
        previous_body = None
        if md_path.exists():
            previous_frontmatter, previous_body = frontmatter.parse(md_path.read_text(encoding="utf-8"))
        targets[news_item_id] = ReconvertTarget(
            news_item_id=news_item_id,
            source_format=inferred_format,
            raw_path=raw_path,
            md_path=md_path,
            target_date=target_date,
            origin="failed",
            failure_reason=reasons.get(news_item_id),
            previous_frontmatter=previous_frontmatter,
            previous_body=previous_body,
        )
    return targets


def _load_version_targets(*, data_root: Path, target_version: str, source_format: str) -> list[ReconvertTarget]:
    db_path = data_root / "fetch-log" / "checksums.db"
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT news_item_id, govpress_version, source_format FROM checksums WHERE govpress_version IS NOT NULL"
    ).fetchall()
    conn.close()

    wanted: list[ReconvertTarget] = []
    for news_item_id, govpress_version, stored_format in rows:
        if source_format != "all" and stored_format != source_format:
            continue
        if _version_gte(str(govpress_version), target_version):
            continue
        md_path = _find_existing_md(data_root, str(news_item_id))
        if md_path is None or not md_path.exists():
            continue
        fm, body = frontmatter.parse(md_path.read_text(encoding="utf-8"))
        raw_rel = fm.get("raw_path", "")
        raw_path = data_root.parent / raw_rel if raw_rel.startswith("data/") else data_root / raw_rel
        if not raw_path.exists():
            continue
        approve_date = fm.get("approve_date")
        target_date = date.fromisoformat(approve_date[:10]) if approve_date and ISO_DATE_RE.match(approve_date[:10]) else None
        wanted.append(
            ReconvertTarget(
                news_item_id=str(news_item_id),
                source_format=str(stored_format),
                raw_path=raw_path,
                md_path=md_path,
                target_date=target_date,
                origin="target_version",
                previous_frontmatter=fm,
                previous_body=body,
            )
        )
    return wanted


def _load_conversion_failed_dates(fetch_log_root: Path) -> dict[str, date]:
    targets: dict[str, date] = {}
    for name in FAILED_LOGS:
        path = fetch_log_root / name
        if not path.exists():
            continue
        for row in _iter_jsonl(path):
            if row.get("status") != "conversion_failed":
                continue
            targets[str(row["news_item_id"])] = date.fromisoformat(str(row["target_date"]))
    return targets


def _load_failed_reasons(path: Path) -> dict[str, str]:
    reasons: dict[str, str] = {}
    if not path.exists():
        return reasons
    for row in _iter_jsonl(path):
        reason = str(row.get("reason", ""))
        if reason.startswith("conversion_failed:"):
            reasons[str(row["news_item_id"])] = reason
    return reasons


def _locate_failed_raw(data_root: Path, news_item_id: str, target_date: date) -> tuple[Path, str]:
    yyyy = target_date.strftime("%Y")
    mm = target_date.strftime("%m")
    hwpx = data_root / "raw" / yyyy / mm / f"{news_item_id}.hwpx"
    if hwpx.exists():
        return hwpx, "hwpx"
    pdf = data_root / "raw" / yyyy / mm / f"{news_item_id}.pdf"
    if pdf.exists():
        return pdf, "pdf"
    for ext in ("hwpx", "pdf", "hwp"):
        matches = list((data_root / "raw").glob(f"**/{news_item_id}.{ext}"))
        if matches:
            return matches[0], ext
    return hwpx, "hwpx"


def _find_existing_md(data_root: Path, news_item_id: str) -> Path | None:
    matches = list((data_root / "md").glob(f"**/{news_item_id}.md"))
    if not matches:
        return None
    return matches[0]


def _load_metadata_for_targets(targets: list[ReconvertTarget]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    need_api_by_date: dict[date, set[str]] = {}

    for target in targets:
        if target.previous_frontmatter is not None:
            metadata[target.news_item_id] = _item_from_frontmatter(target.previous_frontmatter)
        elif target.target_date is not None:
            need_api_by_date.setdefault(target.target_date, set()).add(target.news_item_id)

    if not need_api_by_date:
        return metadata

    service_key = os.environ["GOVPRESS_POLICY_BRIEFING_SERVICE_KEY"]
    client = PolicyBriefingClient(service_key=service_key, timeout_seconds=8)
    list_items = bulk_ingest._list_items_with_retry(client)
    for target_date in sorted(need_api_by_date):
        items = list_items(target_date)
        item_map = {str(item.news_item_id): item for item in items}
        for news_item_id in need_api_by_date[target_date]:
            item = item_map.get(news_item_id)
            if item is not None:
                metadata[news_item_id] = item
    return metadata


def _item_from_frontmatter(fm: dict[str, str]) -> Any:
    approve_date = datetime.fromisoformat(fm["approve_date"]).strftime("%m/%d/%Y %H:%M:%S")
    return SimpleNamespace(
        news_item_id=str(fm["id"]),
        title=fm["title"],
        department=fm["department"],
        approve_date=approve_date,
        original_url=fm["original_url"],
    )


def _reconvert_one(
    *,
    target: ReconvertTarget,
    metadata: Any | None,
    data_root: Path,
    checksum_store: checksums.Store,
    dry_run: bool,
    show_diff: bool,
) -> ReconvertResult:
    if not target.raw_path.exists():
        return ReconvertResult(
            news_item_id=target.news_item_id,
            source_format=target.source_format,
            status="raw_missing",
            note=f"raw file not found: {target.raw_path}",
        )
    if metadata is None:
        return ReconvertResult(
            news_item_id=target.news_item_id,
            source_format=target.source_format,
            status="item_metadata_missing",
            note="item metadata not found",
        )

    started = datetime.now(UTC)
    raw_bytes = target.raw_path.read_bytes()
    sha256 = bulk_ingest.hashlib.sha256(raw_bytes).hexdigest()
    old_body = target.previous_body or ""

    try:
        new_body = bulk_ingest._convert_raw_to_md(target.raw_path, source_format=target.source_format)
    except Exception as exc:
        return ReconvertResult(
            news_item_id=target.news_item_id,
            source_format=target.source_format,
            status="conversion_failed",
            note=f"{type(exc).__name__}: {exc}",
        )

    guard = _check_regression(old_body, new_body)
    if not guard["ok"]:
        return ReconvertResult(
            news_item_id=target.news_item_id,
            source_format=target.source_format,
            status="skip_regression_guard",
            note=guard["reason"],
            body_drop_ratio=guard["body_drop_ratio"],
            table_drop_ratio=guard["table_drop_ratio"],
        )

    if show_diff:
        _print_diff(target.news_item_id, old_body, new_body)

    govpress_version, govpress_commit = bulk_ingest._converter_metadata()
    existing = checksum_store.get(target.news_item_id)
    revision = existing.revision + 1 if existing else 1
    document = frontmatter.prepend(
        new_body,
        frontmatter.build(
            item=metadata,
            entity_type=entity_classify.classify(metadata.department),
            sha256=sha256,
            revision=revision,
            raw_path=target.raw_path.relative_to(data_root),
            govpress_version=govpress_version,
            govpress_commit=govpress_commit,
            source_format=target.source_format,
        ),
    )

    if not dry_run:
        paths.atomic_write_text(target.md_path, document)
        checksum_store.put(
            news_item_id=target.news_item_id,
            sha256=sha256,
            revision=revision,
            fetched_at=datetime.now(UTC),
            govpress_version=govpress_version,
            govpress_commit=govpress_commit,
            source_format=target.source_format,
            commit=False,
        )

    elapsed = (datetime.now(UTC) - started).total_seconds()
    return ReconvertResult(
        news_item_id=target.news_item_id,
        source_format=target.source_format,
        status="success" if not dry_run else "dry_run_preview",
        duration_seconds=elapsed,
    )


def _check_regression(old_body: str, new_body: str) -> dict[str, Any]:
    if not old_body.strip():
        return {"ok": True, "reason": None, "body_drop_ratio": None, "table_drop_ratio": None}

    old_len = len(old_body.strip())
    new_len = len(new_body.strip())
    body_drop_ratio = ((old_len - new_len) / old_len) if old_len else 0.0

    old_tables = _count_tables(old_body)
    new_tables = _count_tables(new_body)
    table_drop_ratio = ((old_tables - new_tables) / old_tables) if old_tables else 0.0

    reasons: list[str] = []
    if body_drop_ratio > 0.20:
        reasons.append(f"body length dropped by {body_drop_ratio * 100:.1f}%")
    if old_tables > 0 and table_drop_ratio > 0.30:
        reasons.append(f"table count dropped by {table_drop_ratio * 100:.1f}%")
    return {
        "ok": not reasons,
        "reason": "; ".join(reasons) if reasons else None,
        "body_drop_ratio": round(body_drop_ratio, 6),
        "table_drop_ratio": round(table_drop_ratio, 6) if old_tables > 0 else None,
    }


def _count_tables(body: str) -> int:
    html_tables = len(re.findall(r"<table\b", body, flags=re.IGNORECASE))
    markdown_tables = len(re.findall(r"(?m)^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*$", body))
    return html_tables + markdown_tables


def _print_diff(news_item_id: str, old_body: str, new_body: str) -> None:
    print(f"===== diff: {news_item_id} =====")
    diff = difflib.unified_diff(
        old_body.splitlines(),
        new_body.splitlines(),
        fromfile="before",
        tofile="after",
        lineterm="",
    )
    for line in diff:
        print(line)


def _update_stats(stats: RunStats, result: ReconvertResult) -> None:
    if result.status == "success":
        stats.successful += 1
        stats.durations.append(result.duration_seconds)
    elif result.status == "dry_run_preview":
        stats.dry_run_preview += 1
        stats.durations.append(result.duration_seconds)
    elif result.status == "skip_regression_guard":
        stats.skipped_regression += 1
    elif result.status == "item_metadata_missing":
        stats.skipped_metadata_missing += 1
    elif result.status == "raw_missing":
        stats.skipped_raw_missing += 1
    elif result.status == "conversion_failed":
        stats.conversion_failed += 1


def _write_report(
    report_path: Path,
    *,
    stats: RunStats,
    started_at: datetime,
    finished_at: datetime,
    source_format: str,
    dry_run: bool,
    sample: int | None,
    log_path: Path,
) -> None:
    elapsed = (finished_at - started_at).total_seconds()
    processed = stats.successful + stats.dry_run_preview + stats.skipped_regression + stats.skipped_metadata_missing + stats.skipped_raw_missing + stats.conversion_failed
    throughput_per_min = processed / (elapsed / 60) if elapsed > 0 else 0.0
    lines = [
        "# Reconvert Report",
        "",
        f"- mode: {'dry-run' if dry_run else 'write'}",
        f"- source_format filter: `{source_format}`",
        f"- sample: `{sample if sample is not None else 'all'}`",
        f"- started_at: `{started_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}`",
        f"- finished_at: `{finished_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}`",
        f"- elapsed_seconds: `{elapsed:.2f}`",
        f"- processed: `{processed}`",
        f"- success: `{stats.successful}`",
        f"- dry_run_preview: `{stats.dry_run_preview}`",
        f"- skip_regression_guard: `{stats.skipped_regression}`",
        f"- item_metadata_missing: `{stats.skipped_metadata_missing}`",
        f"- raw_missing: `{stats.skipped_raw_missing}`",
        f"- conversion_failed: `{stats.conversion_failed}`",
        f"- throughput: `{throughput_per_min:.2f} items/min`",
        f"- mean_duration: `{(sum(stats.durations) / len(stats.durations)) if stats.durations else 0.0:.3f} sec/item`",
        f"- log_json: `{log_path}`",
    ]
    paths.atomic_write_text(report_path, "\n".join(lines) + "\n")


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    paths.append_text_line(path, json.dumps(row, ensure_ascii=False) + "\n")


def _version_gte(left: str, right: str) -> bool:
    return _version_tuple(left) >= _version_tuple(right)


def _version_tuple(text: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", text)
    return tuple(int(part) for part in parts) if parts else (0,)


if __name__ == "__main__":
    raise SystemExit(main())
