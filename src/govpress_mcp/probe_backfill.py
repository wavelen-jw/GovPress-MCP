"""Metadata-only probe for expanding GovPress backfill coverage."""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Iterator

from govpress_mcp import paths, ratelimit
from govpress_mcp.vendored.policy_briefing import (
    PolicyBriefingAttachment,
    PolicyBriefingClient,
    PolicyBriefingItem,
)


FORBIDDEN_HOSTS = ("api2.govpress.cloud",)
HEARTBEAT_INTERVAL_SECONDS = 60.0
BASELINE_DAYS = 1827
BASELINE_DOCS = 130012
BASELINE_RAW_GIB = 250.30
BASELINE_COLLECT_HOURS = 23.89
BASELINE_INDEX_DOCS_PER_MIN = 116.0

_ORIGINAL_URLOPEN = urllib.request.urlopen
_FORBIDDEN_PATCH_INSTALLED = False
_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST_MONOTONIC = 0.0


@dataclass
class DateSummary:
    target_date: str
    item_count: int
    extension_counts: Counter[str] = field(default_factory=Counter)
    selected_format_counts: Counter[str] = field(default_factory=Counter)
    error: str | None = None
    duration_seconds: float = 0.0

    def to_json(self) -> dict[str, object]:
        return {
            "event": "date_summary",
            "target_date": self.target_date,
            "item_count": self.item_count,
            "extension_counts": _ordered_counts(self.extension_counts, EXTENSION_KEYS),
            "selected_format_counts": _ordered_counts(self.selected_format_counts, SELECTED_FORMAT_KEYS),
            "error": self.error,
            "duration_seconds": round(self.duration_seconds, 3),
        }


@dataclass
class ProbeAggregate:
    start_date: date
    end_date: date
    total_days: int
    completed_days: int = 0
    successful_days: int = 0
    failed_days: int = 0
    total_items: int = 0
    extension_counts: Counter[str] = field(default_factory=Counter)
    selected_format_counts: Counter[str] = field(default_factory=Counter)
    yearly_items: Counter[str] = field(default_factory=Counter)
    yearly_extension_counts: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    yearly_selected_format_counts: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    failures: list[tuple[str, str]] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def remaining_days(self) -> int:
        return max(self.total_days - self.completed_days, 0)


EXTENSION_KEYS = (".hwpx", ".hwp", ".pdf", ".odt", "none", "other")
SELECTED_FORMAT_KEYS = ("hwpx", "hwp", "pdf", "odt_only", "no_attachments", "other")


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if stripped:
            self.parts.append(stripped)

    def text(self) -> str:
        return " ".join(self.parts)


def _parse_iso_date(text: str) -> date:
    return datetime.strptime(text, "%Y-%m-%d").date()


def _parse_date_range(text: str) -> tuple[date, date]:
    start_text, sep, end_text = text.partition("..")
    if sep != ".." or not start_text or not end_text:
        raise SystemExit("--date-range 형식은 YYYY-MM-DD..YYYY-MM-DD 이어야 합니다.")
    start_date = _parse_iso_date(start_text)
    end_date = _parse_iso_date(end_text)
    if end_date < start_date:
        raise SystemExit("--date-range 종료일이 시작일보다 빠릅니다.")
    return start_date, end_date


def _iter_dates(start_date: date, end_date: date) -> Iterator[date]:
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def _normalize_extension(extension: str) -> str:
    lower = (extension or "").lower()
    if lower in {".hwpx", ".hwp", ".pdf", ".odt"}:
        return lower
    return "other"


def _selected_format(item: PolicyBriefingItem) -> str:
    attachments = item.attachments
    if not attachments:
        return "no_attachments"
    extensions = {_normalize_extension(attachment.extension) for attachment in attachments}
    if ".hwpx" in extensions:
        return "hwpx"
    if ".hwp" in extensions:
        return "hwp"
    if ".pdf" in extensions:
        return "pdf"
    if extensions == {".odt"}:
        return "odt_only"
    return "other"


def summarize_items(target_date: date, items: Iterable[PolicyBriefingItem], *, duration_seconds: float = 0.0) -> DateSummary:
    extension_counts: Counter[str] = Counter()
    selected_counts: Counter[str] = Counter()
    item_count = 0
    for item in items:
        item_count += 1
        if not item.attachments:
            extension_counts["none"] += 1
        else:
            for attachment in item.attachments:
                extension_counts[_normalize_extension(attachment.extension)] += 1
        selected_counts[_selected_format(item)] += 1
    return DateSummary(
        target_date=target_date.isoformat(),
        item_count=item_count,
        extension_counts=extension_counts,
        selected_format_counts=selected_counts,
        duration_seconds=duration_seconds,
    )


def item_metadata_rows(target_date: date, items: Iterable[PolicyBriefingItem]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in items:
        data_contents_text = html_to_text(item.data_contents)
        rows.append(
            {
                "event": "item_metadata",
                "target_date": target_date.isoformat(),
                "news_item_id": item.news_item_id,
                "title": item.title,
                "department": item.department,
                "approve_date": item.approve_date,
                "original_url": item.original_url,
                "data_contents_html": item.data_contents,
                "data_contents_text": data_contents_text,
                "data_contents_text_length": len(data_contents_text),
                "api_fields": item.api_fields or {},
                "selected_format": _selected_format(item),
                "attachments": [
                    {
                        "file_name": attachment.file_name,
                        "file_url": attachment.file_url,
                        "extension": _normalize_extension(attachment.extension),
                        "is_appendix": attachment.is_appendix,
                    }
                    for attachment in item.attachments
                ],
            }
        )
    return rows


def html_to_text(html: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(unescape(html or ""))
    parser.close()
    text = parser.text()
    if text:
        return text
    return " ".join(unescape(html or "").split())


def failed_summary(target_date: date, error: Exception, *, duration_seconds: float) -> DateSummary:
    return DateSummary(
        target_date=target_date.isoformat(),
        item_count=0,
        error=f"{type(error).__name__}: {error}",
        duration_seconds=duration_seconds,
    )


def _ordered_counts(counter: Counter[str], keys: tuple[str, ...]) -> dict[str, int]:
    ordered = {key: int(counter.get(key, 0)) for key in keys}
    for key in sorted(counter):
        if key not in ordered:
            ordered[key] = int(counter[key])
    return ordered


def load_completed_dates(log_path: Path) -> set[str]:
    if not log_path.exists():
        return set()
    completed: set[str] = set()
    with log_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("event") == "date_summary" and payload.get("target_date"):
                completed.add(str(payload["target_date"]))
    return completed


def aggregate_log(log_path: Path, start_date: date, end_date: date) -> ProbeAggregate:
    aggregate = ProbeAggregate(
        start_date=start_date,
        end_date=end_date,
        total_days=(end_date - start_date).days + 1,
    )
    if not log_path.exists():
        return aggregate

    latest_by_date: dict[str, dict[str, object]] = {}
    with log_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("event") != "date_summary":
                continue
            target_date = str(payload.get("target_date") or "")
            if not target_date:
                continue
            latest_by_date[target_date] = payload

    for target_date in sorted(latest_by_date):
        payload = latest_by_date[target_date]
        item_count = int(payload.get("item_count") or 0)
        error = payload.get("error")
        aggregate.completed_days += 1
        aggregate.total_items += item_count
        aggregate.duration_seconds += float(payload.get("duration_seconds") or 0.0)
        year = target_date[:4]
        aggregate.yearly_items[year] += item_count
        if error:
            aggregate.failed_days += 1
            aggregate.failures.append((target_date, str(error)))
        else:
            aggregate.successful_days += 1

        extension_counts = payload.get("extension_counts") or {}
        if isinstance(extension_counts, dict):
            for key, value in extension_counts.items():
                aggregate.extension_counts[str(key)] += int(value or 0)
                aggregate.yearly_extension_counts[year][str(key)] += int(value or 0)

        selected_counts = payload.get("selected_format_counts") or {}
        if isinstance(selected_counts, dict):
            for key, value in selected_counts.items():
                aggregate.selected_format_counts[str(key)] += int(value or 0)
                aggregate.yearly_selected_format_counts[year][str(key)] += int(value or 0)
    return aggregate


def load_failed_dates(log_path: Path) -> list[date]:
    failed: dict[str, date] = {}
    recovered: set[str] = set()
    if not log_path.exists():
        return []
    with log_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("event") != "date_summary":
                continue
            target = str(payload.get("target_date") or "")
            if not target:
                continue
            if payload.get("error"):
                failed[target] = _parse_iso_date(target)
                recovered.discard(target)
            else:
                recovered.add(target)
    for target in recovered:
        failed.pop(target, None)
    return [failed[target] for target in sorted(failed)]


def write_report(report_path: Path, aggregate: ProbeAggregate, *, log_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    estimated = _estimate_expansion(aggregate)
    lines: list[str] = [
        f"# {aggregate.start_date.isoformat()}~{aggregate.end_date.isoformat()} 백필 확장 정찰 보고서",
        "",
        f"- 생성 시각: {datetime.now().isoformat(timespec='seconds')}",
        f"- 대상 범위: {aggregate.start_date.isoformat()}..{aggregate.end_date.isoformat()}",
        f"- 로그: `{log_path.as_posix()}`",
        f"- 전체 날짜: {aggregate.total_days:,}일",
        f"- 처리 완료: {aggregate.completed_days:,}일",
        f"- 성공 날짜: {aggregate.successful_days:,}일",
        f"- 실패 날짜: {aggregate.failed_days:,}일",
        f"- 전체 문서: {aggregate.total_items:,}건",
        "",
        "## 연도별 문서 수",
        "",
        "| 연도 | 문서 수 |",
        "|---|---:|",
    ]
    for year in sorted(aggregate.yearly_items):
        lines.append(f"| {year} | {aggregate.yearly_items[year]:,} |")

    lines.extend(
        [
            "",
            "## 전체 첨부 확장자 분포",
            "",
            "| 확장자 | 건수 |",
            "|---|---:|",
        ]
    )
    for key, value in _ordered_counts(aggregate.extension_counts, EXTENSION_KEYS).items():
        lines.append(f"| {key} | {value:,} |")

    lines.extend(
        [
            "",
            "## 전체 우선 포맷 추정",
            "",
            "| 우선 포맷 | 문서 수 |",
            "|---|---:|",
        ]
    )
    for key, value in _ordered_counts(aggregate.selected_format_counts, SELECTED_FORMAT_KEYS).items():
        lines.append(f"| {key} | {value:,} |")

    lines.extend(
        [
            "",
            "## 연도별 우선 포맷 추정",
            "",
            "| 연도 | hwpx | hwp | pdf | odt_only | no_attachments | other |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for year in sorted(aggregate.yearly_items):
        counts = aggregate.yearly_selected_format_counts.get(year, Counter())
        lines.append(
            "| {year} | {hwpx:,} | {hwp:,} | {pdf:,} | {odt:,} | {none:,} | {other:,} |".format(
                year=year,
                hwpx=counts.get("hwpx", 0),
                hwp=counts.get("hwp", 0),
                pdf=counts.get("pdf", 0),
                odt=counts.get("odt_only", 0),
                none=counts.get("no_attachments", 0),
                other=counts.get("other", 0),
            )
        )

    lines.extend(
        [
            "",
            "## 실패 날짜",
            "",
        ]
    )
    if aggregate.failures:
        lines.extend(f"- {target_date}: {error}" for target_date, error in aggregate.failures)
    else:
        lines.append("- 없음")

    lines.extend(
        [
            "",
            "## 확대 추정",
            "",
            f"- 현재 5년 기준 날짜 배율: {estimated['date_ratio']:.2f}x",
            f"- 현재 5년 기준 문서 배율: {estimated['doc_ratio']:.2f}x",
            f"- 예상 raw 전체 저장량: 약 {estimated['raw_gib']:.1f} GiB",
            f"- 현재 5년치 대비 raw 추가 저장량: 약 {estimated['raw_incremental_gib']:.1f} GiB",
            f"- 예상 HWP COM 변환 대상: {estimated['hwp_targets']:,}건",
            f"- 예상 PDF 변환 대상: {estimated['pdf_targets']:,}건",
            f"- metadata probe 관측 속도: {estimated['probe_days_per_min']:.1f}일/분",
            f"- 전체 수집·변환 예상: 약 {estimated['collect_hours_low']:.1f}~{estimated['collect_hours_high']:.1f}시간",
            f"- Hot 색인 예상: 약 {estimated['index_hours']:.1f}시간",
            "",
            "## 권장 백필 순서",
            "",
            "1. 연도별 물량이 낮은 구간부터 2~4주 단위로 실제 수집 dry-run을 수행한다.",
            "2. HWP 비중이 높은 구간은 서버H COM 변환 대기열 용량을 먼저 산정한다.",
            "3. PDF 비중이 높은 구간은 PDF 변환 실패 유형을 별도 샘플링한 뒤 확대한다.",
            "4. 수집 완료 구간마다 `derive_hot --incremental` 또는 구간 재색인을 수행한다.",
            "",
        ]
    )
    report_path.write_text("\n".join(lines), encoding="utf-8")


def _estimate_expansion(aggregate: ProbeAggregate) -> dict[str, float | int]:
    doc_ratio = aggregate.total_items / BASELINE_DOCS if BASELINE_DOCS else 0.0
    date_ratio = aggregate.total_days / BASELINE_DAYS if BASELINE_DAYS else 0.0
    probe_days_per_min = (aggregate.completed_days / (aggregate.duration_seconds / 60.0)) if aggregate.duration_seconds else 0.0
    raw_gib = BASELINE_RAW_GIB * doc_ratio
    collect_hours = BASELINE_COLLECT_HOURS * max(doc_ratio, date_ratio)
    return {
        "date_ratio": date_ratio,
        "doc_ratio": doc_ratio,
        "raw_gib": raw_gib,
        "raw_incremental_gib": max(raw_gib - BASELINE_RAW_GIB, 0.0),
        "hwp_targets": int(aggregate.selected_format_counts.get("hwp", 0)),
        "pdf_targets": int(aggregate.selected_format_counts.get("pdf", 0)),
        "probe_days_per_min": probe_days_per_min,
        "collect_hours_low": collect_hours * 0.8,
        "collect_hours_high": collect_hours * 1.3,
        "index_hours": (aggregate.total_items / BASELINE_INDEX_DOCS_PER_MIN / 60.0) if BASELINE_INDEX_DOCS_PER_MIN else 0.0,
    }


def _append_jsonl(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _append_jsonl_many(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _install_forbidden_host_guard() -> None:
    global _FORBIDDEN_PATCH_INSTALLED
    if _FORBIDDEN_PATCH_INSTALLED:
        return

    def guarded_urlopen(url: object, *args: object, **kwargs: object) -> object:
        target = getattr(url, "full_url", url)
        hostname = (urllib.parse.urlparse(str(target)).hostname or "").lower()
        if hostname in FORBIDDEN_HOSTS:
            raise RuntimeError(f"FORBIDDEN_HOSTS blocked host={hostname}")
        return _ORIGINAL_URLOPEN(url, *args, **kwargs)

    urllib.request.urlopen = guarded_urlopen
    _FORBIDDEN_PATCH_INSTALLED = True


def _assert_env(data_root: Path) -> None:
    paths.assert_supported_data_root(data_root)
    if not os.environ.get("GOVPRESS_POLICY_BRIEFING_SERVICE_KEY"):
        raise SystemExit("GOVPRESS_POLICY_BRIEFING_SERVICE_KEY 환경변수가 없습니다.")


def _list_items_with_retry(client: PolicyBriefingClient, target_date: date) -> list[PolicyBriefingItem]:
    delay = 1.0
    retryable_statuses = {429, 500, 502, 503, 504}
    for attempt in range(ratelimit.MAX_RETRIES + 1):
        try:
            return client.list_items(target_date)
        except urllib.error.HTTPError as exc:
            if attempt >= ratelimit.MAX_RETRIES or exc.code not in retryable_statuses:
                raise
            time.sleep(delay)
            delay *= 2
        except (TimeoutError, urllib.error.URLError):
            if attempt >= ratelimit.MAX_RETRIES:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable retry state")


def run(args: argparse.Namespace) -> int:
    global _LAST_REQUEST_MONOTONIC
    data_root = args.data_root.expanduser().resolve()
    _assert_env(data_root)
    _install_forbidden_host_guard()
    _LAST_REQUEST_MONOTONIC = 0.0

    start_date, end_date = _parse_date_range(args.date_range)
    target_dates = load_failed_dates(args.retry_errors_from) if args.retry_errors_from else list(_iter_dates(start_date, end_date))
    if args.retry_errors_from and not target_dates:
        print(f"retry complete no_failed_dates={args.retry_errors_from}", flush=True)
        return 0
    if args.sample_days is not None:
        target_dates = target_dates[: args.sample_days]
        if target_dates:
            end_date = target_dates[-1]

    log_path = args.log_json
    report_path = args.report
    completed_dates = load_completed_dates(log_path) if args.resume else set()
    client = PolicyBriefingClient(
        service_key=os.environ["GOVPRESS_POLICY_BRIEFING_SERVICE_KEY"],
        timeout_seconds=args.timeout,
    )

    started_at = time.monotonic()
    last_heartbeat = started_at
    processed_this_run = 0
    total_items_this_run = 0

    pending_dates = [target_date for target_date in target_dates if target_date.isoformat() not in completed_dates]

    def process_date(target_date: date) -> tuple[DateSummary, list[dict[str, object]]]:
        day_started = time.monotonic()
        try:
            _wait_for_request_slot(args.min_interval)
            items = _list_items_with_retry(client, target_date)
            return (
                summarize_items(target_date, items, duration_seconds=time.monotonic() - day_started),
                item_metadata_rows(target_date, items) if args.items_json is not None else [],
            )
        except Exception as exc:  # pragma: no cover - network failures are integration behavior
            return failed_summary(target_date, exc, duration_seconds=time.monotonic() - day_started), []

    def handle_result(summary: DateSummary, item_rows: list[dict[str, object]]) -> None:
        nonlocal last_heartbeat, processed_this_run, total_items_this_run
        _append_jsonl(log_path, summary.to_json())
        if args.items_json is not None and item_rows:
            _append_jsonl_many(args.items_json, item_rows)
        processed_this_run += 1
        total_items_this_run += summary.item_count

        now = time.monotonic()
        if now - last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
            elapsed_minutes = max((now - started_at) / 60.0, 0.001)
            print(
                "heartbeat "
                f"current_date={summary.target_date} "
                f"completed_days={processed_this_run} "
                f"rate_days_per_min={processed_this_run / elapsed_minutes:.2f} "
                f"total_items_so_far={total_items_this_run}",
                flush=True,
            )
            last_heartbeat = now

    if args.workers == 1:
        for target_date in pending_dates:
            summary, item_rows = process_date(target_date)
            handle_result(summary, item_rows)
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(process_date, target_date) for target_date in pending_dates]
            for future in as_completed(futures):
                summary, item_rows = future.result()
                handle_result(summary, item_rows)

    aggregate = aggregate_log(log_path, start_date, end_date)
    write_report(report_path, aggregate, log_path=log_path)
    print(
        "probe complete "
        f"completed_days={aggregate.completed_days} "
        f"failed_days={aggregate.failed_days} "
        f"total_items={aggregate.total_items} "
        f"report={report_path}",
        flush=True,
    )
    return 0


def _wait_for_request_slot(min_interval: float) -> None:
    global _LAST_REQUEST_MONOTONIC
    if min_interval <= 0:
        return
    with _REQUEST_LOCK:
        now = time.monotonic()
        remaining = min_interval - (now - _LAST_REQUEST_MONOTONIC)
        if remaining > 0:
            time.sleep(remaining)
            now = time.monotonic()
        _LAST_REQUEST_MONOTONIC = now


def build_parser() -> argparse.ArgumentParser:
    now_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    parser = argparse.ArgumentParser(description="Metadata-only GovPress backfill expansion probe.")
    parser.add_argument("--date-range", required=True, help="YYYY-MM-DD..YYYY-MM-DD")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--log-json", type=Path, default=Path("data/fetch-log") / f"probe-{now_stamp}.jsonl")
    parser.add_argument("--items-json", type=Path, help="Optional item-level metadata JSONL output.")
    parser.add_argument("--report", type=Path, default=Path("docs/backfill-expansion-probe.md"))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-errors-from", type=Path, help="Process only failed dates from an existing probe summary JSONL.")
    parser.add_argument("--sample-days", type=int)
    parser.add_argument(
        "--min-interval",
        type=float,
        default=ratelimit.MIN_INTERVAL_SECONDS,
        help="Minimum seconds to wait before each API request. Lower values rely on retry backoff.",
    )
    parser.add_argument("--workers", type=int, default=1, help="Concurrent date probes.")
    parser.add_argument("--timeout", type=int, default=8, help="PolicyBriefing API request timeout in seconds.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.sample_days is not None and args.sample_days < 1:
        raise SystemExit("--sample-days는 1 이상이어야 합니다.")
    if args.min_interval < 0:
        raise SystemExit("--min-interval은 0 이상이어야 합니다.")
    if args.workers < 1:
        raise SystemExit("--workers는 1 이상이어야 합니다.")
    if args.timeout < 1:
        raise SystemExit("--timeout은 1 이상이어야 합니다.")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
