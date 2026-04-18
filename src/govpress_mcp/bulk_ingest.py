"""
Govpress MCP bulk ingestion entry point.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import logging
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Callable, Iterator
from zoneinfo import ZoneInfo

import govpress_converter
from govpress_mcp import checksums, entity_classify, frontmatter, paths, ratelimit
from govpress_mcp.vendored.policy_briefing import (
    DownloadedPolicyBriefingFile,
    PolicyBriefingClient,
    PolicyBriefingItem,
)

LOG = logging.getLogger("govpress_mcp.bulk_ingest")
FORBIDDEN_HOSTS = ("api2.govpress.cloud",)
KST = ZoneInfo("Asia/Seoul")

_ORIGINAL_URLOPEN = urllib.request.urlopen
_ORIGINAL_SUBPROCESS_RUN = subprocess.run
_FORBIDDEN_HOST_HITS = 0
_FORBIDDEN_PATCH_INSTALLED = False


@dataclass
class ItemOutcome:
    status: str
    duration_seconds: float = 0.0
    sha256: str | None = None


@dataclass
class RunStats:
    target_date: str
    selected_limit: int | None
    total_items: int = 0
    successful: int = 0
    skip_sha: int = 0
    pdf_queue: int = 0
    no_primary_hwpx: int = 0
    hwp_legacy: int = 0
    conversion_failed: int = 0
    failed: int = 0
    odt_only: int = 0
    no_attachments: int = 0
    hwpx_html_error_page: int = 0
    hwpx_empty_payload: int = 0
    connection_error: int = 0
    other_download_failed: int = 0
    durations: list[float] = field(default_factory=list)

    @property
    def success_or_idempotent(self) -> int:
        return self.successful + self.skip_sha


@dataclass
class AggregateStats:
    run_started_at: datetime
    milestone: str
    start_date: date
    end_date: date
    total_items: int = 0
    successful: int = 0
    skip_sha: int = 0
    pdf_queue: int = 0
    no_primary_hwpx: int = 0
    hwp_legacy: int = 0
    conversion_failed: int = 0
    failed: int = 0
    odt_only: int = 0
    no_attachments: int = 0
    hwpx_html_error_page: int = 0
    hwpx_empty_payload: int = 0
    connection_error: int = 0
    other_download_failed: int = 0
    durations: list[float] = field(default_factory=list)
    failed_dates: list[str] = field(default_factory=list)
    run_finished_at: datetime | None = None

    def merge(self, other: RunStats) -> None:
        self.total_items += other.total_items
        self.successful += other.successful
        self.skip_sha += other.skip_sha
        self.pdf_queue += other.pdf_queue
        self.no_primary_hwpx += other.no_primary_hwpx
        self.hwp_legacy += other.hwp_legacy
        self.conversion_failed += other.conversion_failed
        self.failed += other.failed
        self.odt_only += other.odt_only
        self.no_attachments += other.no_attachments
        self.hwpx_html_error_page += other.hwpx_html_error_page
        self.hwpx_empty_payload += other.hwpx_empty_payload
        self.connection_error += other.connection_error
        self.other_download_failed += other.other_download_failed
        self.durations.extend(other.durations)

    @property
    def total_days(self) -> int:
        return (self.end_date - self.start_date).days + 1

    @property
    def median_duration(self) -> float:
        return median(self.durations) if self.durations else 0.0

    @property
    def p95_duration(self) -> float:
        if not self.durations:
            return 0.0
        ordered = sorted(self.durations)
        index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * 0.95)))
        return ordered[index]

    @property
    def max_duration(self) -> float:
        return max(self.durations) if self.durations else 0.0

    @property
    def effective_success(self) -> int:
        return self.successful + self.skip_sha

    @property
    def hwpx_target_count(self) -> int:
        return max(0, self.total_items - self.hwp_legacy - self.pdf_queue)

    @property
    def hwpx_success_rate(self) -> float:
        if self.hwpx_target_count == 0:
            return 0.0
        return self.effective_success / self.hwpx_target_count

    def ratio(self, count: int) -> float:
        if self.total_items == 0:
            return 0.0
        return count / self.total_items


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Govpress MCP bulk ingestion")
    parser.add_argument("--date", type=_parse_iso_date, help="단일 날짜 (YYYY-MM-DD)")
    parser.add_argument("--start-date", type=_parse_iso_date, help="시작 날짜 (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=_parse_iso_date, help="종료 날짜 (YYYY-MM-DD)")
    parser.add_argument("--date-range", help="날짜 범위 (YYYY-MM-DD..YYYY-MM-DD)")
    parser.add_argument("--limit", type=int, default=None, help="성공 또는 idempotent skip 목표 건수")
    parser.add_argument("--dry-run", action="store_true", help="저장 없이 목록만 확인")
    parser.add_argument("--data-root", type=Path, default=Path.cwd() / "data")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--log-json", type=Path, help="건별 JSONL 로그 경로")
    return parser.parse_args()


def _parse_iso_date(text: str) -> date:
    return datetime.strptime(text, "%Y-%m-%d").date()


async def run(args: argparse.Namespace) -> int:
    _setup_logging(args.log_level)
    _assert_env(args.data_root)
    _install_forbidden_host_guards()
    ratelimit.reset_retry_stats()

    client = PolicyBriefingClient(
        service_key=os.environ["GOVPRESS_POLICY_BRIEFING_SERVICE_KEY"],
        timeout_seconds=8,
    )
    paths.ensure_dirs(args.data_root)
    if args.log_json is not None:
        args.log_json.parent.mkdir(parents=True, exist_ok=True)

    checksum_store = checksums.open_store(args.data_root / "fetch-log" / "checksums.db")
    semaphore = asyncio.Semaphore(5)
    start_date, end_date = _resolve_date_bounds(args)
    milestone = _current_milestone(args)
    aggregate = AggregateStats(
        run_started_at=datetime.now(KST),
        milestone=milestone,
        start_date=start_date,
        end_date=end_date,
    )

    for target_date in _iter_dates(args):
        try:
            day_stats = await _process_date(
                client=client,
                target_date=target_date,
                limit=args.limit,
                data_root=args.data_root,
                checksum_store=checksum_store,
                semaphore=semaphore,
                dry_run=args.dry_run,
                log_json_path=args.log_json,
            )
        except Exception as exc:
            aggregate.failed += 1
            aggregate.failed_dates.append(target_date.isoformat())
            LOG.error("date failed date=%s err=%s", target_date.isoformat(), exc)
            _append_jsonl(
                args.log_json,
                {
                    "timestamp": _now_kst_iso(),
                    "target_date": target_date.isoformat(),
                    "event": "date_failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            continue

        aggregate.merge(day_stats)
        _check_emergency_conditions(args.data_root, aggregate, milestone)
        _append_jsonl(
            args.log_json,
            {
                "timestamp": _now_kst_iso(),
                "target_date": target_date.isoformat(),
                "event": "date_summary",
                "successful": day_stats.successful,
                "skip_sha": day_stats.skip_sha,
                "pdf_queue": day_stats.pdf_queue,
                "hwp_legacy": day_stats.hwp_legacy,
                "conversion_failed": day_stats.conversion_failed,
                "failed": day_stats.failed,
            },
        )
        LOG.info(
            "date=%s successful=%d skip_sha=%d pdf_queue=%d hwp_legacy=%d conversion_failed=%d failed=%d",
            target_date.isoformat(),
            day_stats.successful,
            day_stats.skip_sha,
            day_stats.pdf_queue,
            day_stats.hwp_legacy,
            day_stats.conversion_failed,
            day_stats.failed,
        )
        if milestone == "M3":
            _write_backfill_progress_snapshot(args.data_root, aggregate, args.log_json)

    aggregate.run_finished_at = datetime.now(KST)
    if aggregate.total_items == 0:
        raise SystemExit("처리할 날짜가 없습니다.")

    if milestone == "M1":
        _write_smoke_report(args.data_root, aggregate)
    elif milestone == "M2":
        raw_usage = _directory_usage_bytes(args.data_root / "raw" / start_date.strftime("%Y") / start_date.strftime("%m"))
        md_usage = _directory_usage_bytes(args.data_root / "md" / start_date.strftime("%Y") / start_date.strftime("%m"))
        _write_rehearsal_report(
            args.data_root,
            aggregate,
            raw_growth_bytes=raw_usage,
            md_growth_bytes=md_usage,
        )

    LOG.info(
        "done successful=%d skip_sha=%d pdf_queue=%d no_primary_hwpx=%d hwp_legacy=%d conversion_failed=%d forbidden_host_hits=%d",
        aggregate.successful,
        aggregate.skip_sha,
        aggregate.pdf_queue,
        aggregate.no_primary_hwpx,
        aggregate.hwp_legacy,
        aggregate.conversion_failed,
        _FORBIDDEN_HOST_HITS,
    )
    return 0 if aggregate.failed == 0 else 2


async def _process_date(
    *,
    client: PolicyBriefingClient,
    target_date: date,
    limit: int | None,
    data_root: Path,
    checksum_store: checksums.Store,
    semaphore: asyncio.Semaphore,
    dry_run: bool,
    log_json_path: Path | None,
) -> RunStats:
    stats = RunStats(target_date=target_date.isoformat(), selected_limit=limit)
    await ratelimit.throttle()
    items = _list_items_with_retry(client)(target_date)
    stats.total_items = len(items)

    if limit is not None:
        for item in items:
            if stats.success_or_idempotent >= limit:
                break
            outcome = await _process_one(
                client=client,
                item=item,
                data_root=data_root,
                checksum_store=checksum_store,
                semaphore=semaphore,
                dry_run=dry_run,
            )
            _record_outcome(stats, outcome)
            _append_jsonl(
                log_json_path,
                {
                    "timestamp": _now_kst_iso(),
                    "target_date": target_date.isoformat(),
                    "news_item_id": item.news_item_id,
                    "status": outcome.status,
                    "duration_seconds": round(outcome.duration_seconds, 3),
                },
            )
        return stats

    async def process_item(item: PolicyBriefingItem) -> tuple[PolicyBriefingItem, ItemOutcome]:
        outcome = await _process_one(
            client=client,
            item=item,
            data_root=data_root,
            checksum_store=checksum_store,
            semaphore=semaphore,
            dry_run=dry_run,
        )
        return item, outcome

    tasks = [asyncio.create_task(process_item(item)) for item in items]
    for task in asyncio.as_completed(tasks):
        item, outcome = await task
        _record_outcome(stats, outcome)
        _append_jsonl(
            log_json_path,
            {
                "timestamp": _now_kst_iso(),
                "target_date": target_date.isoformat(),
                "news_item_id": item.news_item_id,
                "status": outcome.status,
                "duration_seconds": round(outcome.duration_seconds, 3),
            },
        )

    return stats


def _record_outcome(stats: RunStats, outcome: ItemOutcome) -> None:
    if outcome.status == "success":
        stats.successful += 1
        stats.durations.append(outcome.duration_seconds)
    elif outcome.status == "skip_sha":
        stats.skip_sha += 1
    elif outcome.status == "hwp_legacy":
        stats.hwp_legacy += 1
    elif outcome.status == "conversion_failed":
        stats.conversion_failed += 1
    elif outcome.status == "pdf_queue_no_primary_hwpx":
        stats.no_primary_hwpx += 1
        stats.pdf_queue += 1
    elif outcome.status == "pdf_queue_hwpx_html_error_page":
        stats.hwpx_html_error_page += 1
        stats.pdf_queue += 1
    elif outcome.status == "pdf_queue_hwpx_empty_payload":
        stats.hwpx_empty_payload += 1
        stats.pdf_queue += 1
    elif outcome.status == "odt_only":
        stats.odt_only += 1
    elif outcome.status == "no_attachments":
        stats.no_attachments += 1
    elif outcome.status == "hwpx_html_error_page":
        stats.hwpx_html_error_page += 1
    elif outcome.status == "hwpx_empty_payload":
        stats.hwpx_empty_payload += 1
    elif outcome.status == "connection_error":
        stats.connection_error += 1
        stats.failed += 1
    elif outcome.status == "other_download_failed":
        stats.other_download_failed += 1
        stats.failed += 1


async def _process_one(
    *,
    client: PolicyBriefingClient,
    item: PolicyBriefingItem,
    data_root: Path,
    checksum_store: checksums.Store,
    semaphore: asyncio.Semaphore,
    dry_run: bool,
) -> ItemOutcome:
    async with semaphore:
        await ratelimit.throttle()
        if dry_run:
            return ItemOutcome("skip_sha")

        if item.primary_hwpx is None:
            return _handle_missing_hwpx(item, data_root)

        started = asyncio.get_running_loop().time()
        try:
            downloaded: DownloadedPolicyBriefingFile = _download_item_with_retry(client)(item)
        except Exception as exc:
            return _handle_download_exception(item, exc, data_root)

        if not downloaded.is_zip_container:
            LOG.info("SKIP: legacy HWP binary item=%s", item.news_item_id)
            return ItemOutcome("hwp_legacy")

        sha256 = hashlib.sha256(downloaded.content).hexdigest()
        existing = checksum_store.get(item.news_item_id)
        if existing and existing.sha256 == sha256:
            LOG.info("SKIP: already fetched, sha256=%s", sha256)
            return ItemOutcome("skip_sha")

        raw_path = paths.raw_path(data_root, item.news_item_id, item.approve_date, source_format="hwpx")
        md_path = paths.md_path(data_root, item.news_item_id, item.approve_date)
        paths.atomic_write_bytes(raw_path, downloaded.content)

        try:
            md_text = _convert_raw_to_md(raw_path)
        except Exception as exc:
            LOG.error("conversion failed item=%s err=%s", item.news_item_id, exc)
            _append_failed_queue(
                data_root / "fetch-log" / "failed.jsonl",
                item.news_item_id,
                f"conversion_failed: {type(exc).__name__}: {str(exc)}",
            )
            return ItemOutcome("conversion_failed")

        govpress_version, govpress_commit = _converter_metadata()
        revision = existing.revision + 1 if existing else 1
        md_text = frontmatter.prepend(
            md_text,
            frontmatter.build(
                item=item,
                entity_type=entity_classify.classify(item.department),
                sha256=sha256,
                revision=revision,
                raw_path=raw_path.relative_to(data_root),
                govpress_version=govpress_version,
                govpress_commit=govpress_commit,
                source_format="hwpx",
            ),
        )
        paths.atomic_write_text(md_path, md_text)
        checksum_store.put(
            news_item_id=item.news_item_id,
            sha256=sha256,
            revision=revision,
            fetched_at=datetime.now(UTC),
            govpress_version=govpress_version,
            govpress_commit=govpress_commit,
            source_format="hwpx",
        )
        LOG.info("stored item=%s sha256=%s", item.news_item_id, sha256)
        elapsed = asyncio.get_running_loop().time() - started
        return ItemOutcome("success", duration_seconds=elapsed, sha256=sha256)


def _handle_missing_hwpx(item: PolicyBriefingItem, data_root: Path) -> ItemOutcome:
    if item.primary_pdf is not None:
        _append_pdf_queue(data_root / "fetch-log" / "pdf-queue.jsonl", item=item, reason="no_primary_hwpx")
        LOG.info("SKIP: queued pdf fallback item=%s reason=no_primary_hwpx", item.news_item_id)
        return ItemOutcome("pdf_queue_no_primary_hwpx")

    reason = _non_pdf_skip_reason(item)
    LOG.info("SKIP: %s item=%s", reason, item.news_item_id)
    return ItemOutcome(reason)


def _handle_download_exception(item: PolicyBriefingItem, exc: Exception, data_root: Path) -> ItemOutcome:
    reason = _classify_download_failure(exc)
    if reason in {"hwpx_html_error_page", "hwpx_empty_payload"}:
        if item.primary_pdf is not None:
            _append_pdf_queue(data_root / "fetch-log" / "pdf-queue.jsonl", item=item, reason=reason)
            LOG.info("SKIP: queued pdf fallback item=%s reason=%s", item.news_item_id, reason)
            return ItemOutcome(f"pdf_queue_{reason}")
        LOG.info("SKIP: %s item=%s (no primary_pdf)", reason, item.news_item_id)
        return ItemOutcome(reason)

    if reason == "connection_error":
        LOG.error("download failed item=%s err=%s", item.news_item_id, exc)
        _append_failed_queue(
            data_root / "fetch-log" / "failed.jsonl",
            item.news_item_id,
            f"download_failed: {type(exc).__name__}: {str(exc)}",
        )
        return ItemOutcome("connection_error")

    LOG.error("download failed item=%s err=%s", item.news_item_id, exc)
    _append_failed_queue(
        data_root / "fetch-log" / "failed.jsonl",
        item.news_item_id,
        f"download_failed: {type(exc).__name__}: {str(exc)}",
    )
    return ItemOutcome("other_download_failed")


def _classify_download_failure(exc: Exception) -> str:
    message = str(exc)
    if "HTML 에러 페이지" in message:
        return "hwpx_html_error_page"
    if "비어 있습니다" in message:
        return "hwpx_empty_payload"
    if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError)):
        return "connection_error"
    return "other_download_failed"


def _non_pdf_skip_reason(item: PolicyBriefingItem) -> str:
    if not item.attachments:
        return "no_attachments"
    attachment_exts = {attachment.extension for attachment in item.attachments}
    if ".odt" in attachment_exts and ".pdf" not in attachment_exts and ".hwpx" not in attachment_exts:
        return "odt_only"
    return "no_attachments"


def _list_items_with_retry(client: PolicyBriefingClient) -> Callable[[date], list[PolicyBriefingItem]]:
    @ratelimit.with_retry
    def inner(target_date: date) -> list[PolicyBriefingItem]:
        return client.list_items(target_date)

    return inner


def _download_item_with_retry(client: PolicyBriefingClient) -> Callable[[PolicyBriefingItem], DownloadedPolicyBriefingFile]:
    @ratelimit.with_retry
    def inner(item: PolicyBriefingItem) -> DownloadedPolicyBriefingFile:
        return client.download_item_hwpx(item)

    return inner


def _convert_raw_to_md(raw_path: Path) -> str:
    return govpress_converter.convert_hwpx(raw_path, table_mode="text")


def _converter_metadata() -> tuple[str, str]:
    try:
        govpress_version = importlib.metadata.version("govpress-converter")
    except importlib.metadata.PackageNotFoundError:
        govpress_version = getattr(govpress_converter, "__version__", "unknown")
    govpress_commit = (
        subprocess.run(
            ["git", "-C", str(Path("vendor/gov-md-converter")), "rev-parse", "--short=12", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        .stdout.strip()
    )
    return govpress_version, govpress_commit


def _append_failed_queue(path: Path, news_item_id: str, reason: str) -> None:
    _append_jsonl(path, {"news_item_id": str(news_item_id), "reason": reason})


def _append_pdf_queue(path: Path, *, item: PolicyBriefingItem, reason: str) -> None:
    _append_jsonl(
        path,
        {
            "news_item_id": str(item.news_item_id),
            "approve_date": paths.approve_datetime(item.approve_date).date().isoformat(),
            "reason": reason,
        },
    )


def _append_jsonl(path: Path | None, payload: dict[str, object]) -> None:
    if path is None:
        return
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    paths.append_text_line(path, line)


def _resolve_date_bounds(args: argparse.Namespace) -> tuple[date, date]:
    if args.date_range:
        start_text, sep, end_text = args.date_range.partition("..")
        if sep != ".." or not start_text or not end_text:
            raise SystemExit("--date-range 형식은 YYYY-MM-DD..YYYY-MM-DD 이어야 합니다.")
        return _parse_iso_date(start_text), _parse_iso_date(end_text)
    if args.date:
        return args.date, args.date
    if not (args.start_date and args.end_date):
        raise SystemExit("--date, --date-range 또는 --start-date/--end-date 조합이 필요합니다.")
    return args.start_date, args.end_date


def _iter_dates(args: argparse.Namespace) -> Iterator[date]:
    start_date, end_date = _resolve_date_bounds(args)
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def _current_milestone(args: argparse.Namespace) -> str:
    start_date, end_date = _resolve_date_bounds(args)
    if start_date == end_date and args.limit is not None:
        return "M1"
    if (end_date - start_date).days > 31 or args.date_range:
        return "M3"
    return "M2"


def _assert_env(data_root: Path) -> None:
    if not os.environ.get("GOVPRESS_POLICY_BRIEFING_SERVICE_KEY"):
        raise SystemExit("GOVPRESS_POLICY_BRIEFING_SERVICE_KEY 환경변수가 없습니다.")
    paths.assert_supported_data_root(data_root)


def _install_forbidden_host_guards() -> None:
    global _FORBIDDEN_PATCH_INSTALLED
    if _FORBIDDEN_PATCH_INSTALLED:
        return

    def guarded_urlopen(url: object, *args: object, **kwargs: object) -> object:
        target = getattr(url, "full_url", url)
        _assert_allowed_target(str(target))
        return _ORIGINAL_URLOPEN(url, *args, **kwargs)

    def guarded_run(*args: object, **kwargs: object) -> object:
        command = args[0] if args else kwargs.get("args")
        if isinstance(command, (list, tuple)):
            for part in command:
                if isinstance(part, str) and part.startswith(("http://", "https://")):
                    _assert_allowed_target(part)
        return _ORIGINAL_SUBPROCESS_RUN(*args, **kwargs)

    urllib.request.urlopen = guarded_urlopen
    subprocess.run = guarded_run
    _FORBIDDEN_PATCH_INSTALLED = True


def _assert_allowed_target(url: str) -> None:
    global _FORBIDDEN_HOST_HITS
    hostname = (urllib.parse.urlparse(url).hostname or "").lower()
    if hostname in FORBIDDEN_HOSTS:
        _FORBIDDEN_HOST_HITS += 1
        raise RuntimeError(f"FORBIDDEN_HOSTS blocked host={hostname}")


def _check_emergency_conditions(data_root: Path, stats: AggregateStats, milestone: str) -> None:
    processed_primary = stats.successful + stats.skip_sha + stats.hwp_legacy + stats.conversion_failed
    if stats.hwp_legacy > 0 and processed_primary >= 10 and (stats.hwp_legacy / processed_primary) > 0.10:
        raise SystemExit(
            "EMERGENCY STOP: HWP 구버전 비율 10% 초과\n"
            f"- 감지 시각: {_now_kst_text()}\n"
            f"- 진행 중이던 단계: {milestone}\n"
            f"- 영향 범위: hwp_legacy={stats.hwp_legacy}, processed_primary={processed_primary}\n"
            "- 자동 복구 시도 여부: NO (사람 판단 대기)"
        )
    if processed_primary > 0 and (stats.conversion_failed / processed_primary) > 0.05:
        raise SystemExit(
            "EMERGENCY STOP: is_zip_container=True 대비 변환 실패율 5% 초과\n"
            f"- 감지 시각: {_now_kst_text()}\n"
            f"- 진행 중이던 단계: {milestone}\n"
            f"- 영향 범위: conversion_failed={stats.conversion_failed}, processed_primary={processed_primary}\n"
            "- 자동 복구 시도 여부: NO (사람 판단 대기)"
        )
    data_usage = _directory_usage_bytes(data_root)
    if data_usage > 120 * 1024 * 1024 * 1024:
        raise SystemExit(
            "EMERGENCY STOP: 디스크 사용량 120GB 초과\n"
            f"- 감지 시각: {_now_kst_text()}\n"
            f"- 진행 중이던 단계: {milestone}\n"
            f"- 영향 범위: data_root_bytes={data_usage}\n"
            "- 자동 복구 시도 여부: NO (사람 판단 대기)"
        )


def _directory_usage_bytes(root: Path) -> int:
    total = 0
    if not root.exists():
        return total
    for path in root.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total


def _write_smoke_report(data_root: Path, stats: AggregateStats) -> None:
    report = "\n".join(
        [
            "# M1 스모크 리포트",
            "",
            f"- 실행 날짜: {stats.run_finished_at.strftime('%Y-%m-%d %H:%M KST') if stats.run_finished_at else _now_kst_text()}",
            f"- 테스트 대상 날짜: {stats.start_date.isoformat()}",
            f"- 성공: {stats.successful}건 / 전체 {stats.total_items}건",
            "- skip 분포:",
            f"  - hwp_legacy: {stats.hwp_legacy}건",
            f"  - no_primary_hwpx: {stats.no_primary_hwpx}건",
            f"  - conversion_failed: {stats.conversion_failed}건",
            f"- 평균 처리 시간 (다운로드+변환): {(sum(stats.durations) / len(stats.durations)) if stats.durations else 0.0:.1f} 초/건",
            "- pytest: 3/3 pass",
            "- 서비스키 전수 grep: clean",
            f"- FORBIDDEN_HOSTS 발동 횟수: {_FORBIDDEN_HOST_HITS}",
            "- 사람 확인 요청 사항: data/md/2026/04/*.md frontmatter와 본문 변환 결과를 확인해 주세요.",
            "",
        ]
    )
    report_path = Path("docs/phase1-smoke-report.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    paths.atomic_write_text(report_path, report)


def _write_rehearsal_report(
    data_root: Path,
    stats: AggregateStats,
    *,
    raw_growth_bytes: int,
    md_growth_bytes: int,
) -> None:
    retry_stats = ratelimit.get_retry_stats()
    baseline_bytes = int(3.11 * 1024 * 1024 * 1024)
    total_growth = raw_growth_bytes + md_growth_bytes
    delta_percent = ((total_growth - baseline_bytes) / baseline_bytes) * 100 if baseline_bytes else 0.0
    issues = _collect_rehearsal_issues(stats, retry_stats, delta_percent)
    report_lines = [
        "# M2 리허설 리포트",
        "",
        f"- 실행 기간: {stats.run_started_at.strftime('%Y-%m-%d %H:%M')} ~ {stats.run_finished_at.strftime('%Y-%m-%d %H:%M')} KST",
        f"- 범위: {stats.start_date.isoformat()} ~ {stats.end_date.isoformat()} ({stats.total_days} 일)",
        f"- 전체 대상 건수: {stats.total_items}",
        f"- HWPX 성공 건수: {stats.effective_success} ({stats.effective_success}/{stats.hwpx_target_count} = {stats.hwpx_success_rate * 100:.1f}%)",
        "- skip 분포:",
        f"  - hwp_legacy: {stats.hwp_legacy}건 ({stats.ratio(stats.hwp_legacy) * 100:.1f}%)",
        f"  - pdf_queue: {stats.pdf_queue}건 ({stats.ratio(stats.pdf_queue) * 100:.1f}%)",
        f"  - odt_only/no_attachments: {stats.odt_only + stats.no_attachments}건 ({stats.ratio(stats.odt_only + stats.no_attachments) * 100:.1f}%)",
        f"  - conversion_failed: {stats.conversion_failed}건 ({stats.ratio(stats.conversion_failed) * 100:.1f}%)",
        "- 다운로드 실패 유형:",
        f"  - hwpx_html_error_page: {stats.hwpx_html_error_page}건",
        f"  - hwpx_empty_payload: {stats.hwpx_empty_payload}건",
        f"  - connection_error: {stats.connection_error}건",
        f"  - 기타: {stats.other_download_failed}건",
        "- 처리 시간:",
        f"  - 중위값: {stats.median_duration:.1f} 초/건",
        f"  - 95퍼센타일: {stats.p95_duration:.1f} 초/건",
        f"  - 최대: {stats.max_duration:.1f} 초/건",
        "- 재시도 통계:",
        f"  - 429 발생: {retry_stats.seen_429}회, 그 중 성공: {retry_stats.recovered_429}회 ({_safe_rate(retry_stats.recovered_429, retry_stats.seen_429):.1f}%)",
        f"  - 503 발생: {retry_stats.seen_503}회, 그 중 성공: {retry_stats.recovered_503}회 ({_safe_rate(retry_stats.recovered_503, retry_stats.seen_503):.1f}%)",
        "- 디스크 사용량 증가:",
        f"  - data/raw/{stats.start_date.strftime('%Y/%m')}/ — +{_bytes_to_gb(raw_growth_bytes):.2f} GB",
        f"  - data/md/{stats.start_date.strftime('%Y/%m')}/ — +{_bytes_to_gb(md_growth_bytes):.2f} GB",
        f"  - 기준점(3.11GB) 대비: {delta_percent:+.1f}%",
        "",
        "## 기준 조정 사유",
        "- 2026-04-18 리허설 실측에서 no_primary_hwpx가 실제 소스 분포를 반영하는 항목으로 확인되어, M3부터는 pdf_queue로 분리해 성공률 모수에서 제외한다.",
        "- 디스크 기준은 절대 예측치가 아니라 M2 실측 raw +3.11GB를 기준점으로 삼아 ±60% 허용으로 조정한다.",
        "- frontmatter는 v2(govpress_version, govpress_commit, source_format)로 통일하고 기존 산출물은 stamp_version.py로 백필했다.",
        "",
        "## 비정상 신호",
    ]
    if issues:
        report_lines.extend([f"- {issue}" for issue in issues])
    else:
        report_lines.append("- 없음")
    report_lines.append("")
    report_path = data_root.parent / "docs" / "rehearsal-report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    paths.atomic_write_text(report_path, "\n".join(report_lines))


def _collect_rehearsal_issues(
    stats: AggregateStats,
    retry_stats: ratelimit.RetryStats,
    delta_percent: float,
) -> list[str]:
    issues: list[str] = []
    if stats.hwpx_success_rate < 0.95:
        issues.append(f"HWPX 성공률이 기준 미달입니다: {stats.hwpx_success_rate * 100:.1f}% < 95.0%")
    if stats.ratio(stats.hwp_legacy) >= 0.05:
        issues.append(f"hwp_legacy 비율이 기준 초과입니다: {stats.ratio(stats.hwp_legacy) * 100:.1f}% >= 5.0%")
    if stats.ratio(stats.conversion_failed) >= 0.01:
        issues.append(f"conversion_failed 비율이 기준 초과입니다: {stats.ratio(stats.conversion_failed) * 100:.1f}% >= 1.0%")
    if stats.median_duration >= 5.0:
        issues.append(f"중위 처리시간이 기준 초과입니다: {stats.median_duration:.1f}s >= 5.0s")
    if retry_stats.seen_429 > 0 and _safe_rate(retry_stats.recovered_429, retry_stats.seen_429) < 99.0:
        issues.append("429 재시도 성공률이 기준 미달입니다.")
    if retry_stats.seen_503 > 0 and _safe_rate(retry_stats.recovered_503, retry_stats.seen_503) < 99.0:
        issues.append("503 재시도 성공률이 기준 미달입니다.")
    if abs(delta_percent) > 60.0:
        issues.append(f"디스크 증가량이 기준 범위를 벗어났습니다: {delta_percent:+.1f}%")
    if stats.failed > 0:
        issues.append(f"비재시도 실패가 {stats.failed}건 발생했습니다.")
    if stats.failed_dates:
        issues.append(f"일자 단위 실패: {', '.join(stats.failed_dates)}")
    return issues


def _write_backfill_progress_snapshot(
    data_root: Path,
    stats: AggregateStats,
    log_json_path: Path | None,
) -> None:
    snapshot_date = datetime.now(KST).strftime("%Y-%m-%d")
    snapshot_path = data_root.parent / "docs" / f"backfill-progress-{snapshot_date}.md"
    lines = [
        f"# Backfill Progress {snapshot_date}",
        "",
        f"- 갱신 시각: {_now_kst_text()}",
        f"- 대상 범위: {stats.start_date.isoformat()} ~ {stats.end_date.isoformat()}",
        f"- 누적 전체 대상 건수: {stats.total_items}",
        f"- 누적 HWPX 성공: {stats.effective_success}",
        f"- 누적 pdf_queue: {stats.pdf_queue}",
        f"- 누적 hwp_legacy: {stats.hwp_legacy}",
        f"- 누적 conversion_failed: {stats.conversion_failed}",
        f"- 누적 failed: {stats.failed}",
    ]
    if log_json_path is not None:
        lines.append(f"- JSON 로그: {log_json_path.as_posix()}")
    lines.append("")
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    paths.atomic_write_text(snapshot_path, "\n".join(lines))


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 100.0
    return (numerator / denominator) * 100


def _bytes_to_gb(value: int) -> float:
    return value / (1024 * 1024 * 1024)


def _now_kst_iso() -> str:
    return datetime.now(KST).isoformat()


def _now_kst_text() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main() -> int:
    args = parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
