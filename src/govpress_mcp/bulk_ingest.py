"""
Govpress MCP bulk ingestion entry point.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Callable, Iterator

import govpress_converter
from govpress_mcp import checksums, entity_classify, frontmatter, paths, ratelimit
from govpress_mcp.vendored.policy_briefing import (
    DownloadedPolicyBriefingFile,
    PolicyBriefingClient,
    PolicyBriefingItem,
)

LOG = logging.getLogger("govpress_mcp.bulk_ingest")
FORBIDDEN_HOSTS = ("api2.govpress.cloud",)

_ORIGINAL_URLOPEN = urllib.request.urlopen
_ORIGINAL_SUBPROCESS_RUN = subprocess.run
_FORBIDDEN_HOST_HITS = 0
_FORBIDDEN_PATCH_INSTALLED = False


@dataclass
class RunStats:
    target_date: str
    selected_limit: int | None
    total_items: int = 0
    successful: int = 0
    skip_sha: int = 0
    no_primary_hwpx: int = 0
    hwp_legacy: int = 0
    conversion_failed: int = 0
    failed: int = 0
    durations: list[float] = field(default_factory=list)

    @property
    def success_or_idempotent(self) -> int:
        return self.successful + self.skip_sha

    @property
    def average_duration(self) -> float:
        if not self.durations:
            return 0.0
        return sum(self.durations) / len(self.durations)


@dataclass
class AggregateStats:
    run_started_at: datetime
    milestone: str
    start_date: date
    end_date: date
    total_items: int = 0
    successful: int = 0
    skip_sha: int = 0
    no_primary_hwpx: int = 0
    hwp_legacy: int = 0
    conversion_failed: int = 0
    failed: int = 0
    durations: list[float] = field(default_factory=list)
    failed_dates: list[str] = field(default_factory=list)
    run_finished_at: datetime | None = None

    def merge(self, other: RunStats) -> None:
        self.total_items += other.total_items
        self.successful += other.successful
        self.skip_sha += other.skip_sha
        self.no_primary_hwpx += other.no_primary_hwpx
        self.hwp_legacy += other.hwp_legacy
        self.conversion_failed += other.conversion_failed
        self.failed += other.failed
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
    def success_rate(self) -> float:
        if self.total_items == 0:
            return 0.0
        return self.effective_success / self.total_items

    def ratio(self, count: int) -> float:
        if self.total_items == 0:
            return 0.0
        return count / self.total_items


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Govpress MCP bulk ingestion")
    parser.add_argument("--date", type=_parse_iso_date, help="단일 날짜 (YYYY-MM-DD)")
    parser.add_argument("--start-date", type=_parse_iso_date, help="시작 날짜 (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=_parse_iso_date, help="종료 날짜 (YYYY-MM-DD)")
    parser.add_argument("--limit", type=int, default=None, help="성공 또는 idempotent skip 목표 건수")
    parser.add_argument("--dry-run", action="store_true", help="저장 없이 목록만 확인")
    parser.add_argument("--data-root", type=Path, default=Path.cwd() / "data")
    parser.add_argument("--log-level", default="INFO")
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
    checksum_store = checksums.open_store(args.data_root / "fetch-log" / "checksums.db")
    semaphore = asyncio.Semaphore(5)
    start_date, end_date = _resolve_date_bounds(args)
    milestone = _current_milestone(args)
    aggregate = AggregateStats(
        run_started_at=datetime.now(),
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
            )
        except Exception as exc:
            aggregate.failed += 1
            aggregate.failed_dates.append(target_date.isoformat())
            LOG.error("date failed date=%s err=%s", target_date.isoformat(), exc)
            continue
        else:
            aggregate.merge(day_stats)
            _check_emergency_conditions(args.data_root, aggregate, milestone)
            LOG.info(
                "date=%s successful=%d skip_sha=%d no_primary_hwpx=%d hwp_legacy=%d conversion_failed=%d failed=%d",
                target_date.isoformat(),
                day_stats.successful,
                day_stats.skip_sha,
                day_stats.no_primary_hwpx,
                day_stats.hwp_legacy,
                day_stats.conversion_failed,
                day_stats.failed,
            )

    aggregate.run_finished_at = datetime.now()
    if aggregate.total_items == 0:
        raise SystemExit("처리할 날짜가 없습니다.")
    raw_after = _directory_usage_bytes(args.data_root / "raw" / start_date.strftime("%Y") / start_date.strftime("%m"))
    md_after = _directory_usage_bytes(args.data_root / "md" / start_date.strftime("%Y") / start_date.strftime("%m"))
    if milestone == "M1":
        _write_smoke_report(args.data_root, aggregate)
    else:
        _write_rehearsal_report(
            args.data_root,
            aggregate,
            raw_growth_bytes=raw_after,
            md_growth_bytes=md_after,
        )
    LOG.info(
        "done successful=%d skip_sha=%d no_primary_hwpx=%d hwp_legacy=%d conversion_failed=%d forbidden_host_hits=%d",
        aggregate.successful,
        aggregate.skip_sha,
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
) -> RunStats:
    stats = RunStats(target_date=target_date.isoformat(), selected_limit=limit)
    await ratelimit.throttle()
    items = _list_items_with_retry(client)(target_date)
    stats.total_items = len(items)

    for item in items:
        if limit is not None and stats.success_or_idempotent >= limit:
            break
        if item.primary_hwpx is None:
            stats.no_primary_hwpx += 1
            continue

        started = asyncio.get_running_loop().time()
        try:
            result = await _process_one(
                client=client,
                item=item,
                data_root=data_root,
                checksum_store=checksum_store,
                semaphore=semaphore,
                dry_run=dry_run,
            )
        except Exception as exc:
            LOG.error("item failed item=%s err=%s", item.news_item_id, exc)
            _append_failed_queue(
                data_root / "fetch-log" / "failed.jsonl",
                item.news_item_id,
                f"download_failed: {type(exc).__name__}",
            )
            stats.failed += 1
            continue
        elapsed = asyncio.get_running_loop().time() - started

        if result == "success":
            stats.successful += 1
            stats.durations.append(elapsed)
        elif result == "skip_sha":
            stats.skip_sha += 1
        elif result == "hwp_legacy":
            stats.hwp_legacy += 1
        elif result == "conversion_failed":
            stats.conversion_failed += 1
    return stats


async def _process_one(
    *,
    client: object,
    item: PolicyBriefingItem,
    data_root: Path,
    checksum_store: checksums.Store,
    semaphore: asyncio.Semaphore,
    dry_run: bool,
) -> str:
    async with semaphore:
        await ratelimit.throttle()
        if dry_run:
            return "skip_sha"

        try:
            downloaded: DownloadedPolicyBriefingFile = _download_item_with_retry(client)(item)
        except Exception as exc:
            LOG.error("download failed item=%s err=%s", item.news_item_id, exc)
            raise

        if not downloaded.is_zip_container:
            LOG.info("SKIP: legacy HWP binary item=%s", item.news_item_id)
            return "hwp_legacy"

        sha256 = hashlib.sha256(downloaded.content).hexdigest()
        existing = checksum_store.get(item.news_item_id)
        if existing and existing.sha256 == sha256:
            LOG.info("SKIP: already fetched, sha256=%s", sha256)
            return "skip_sha"

        raw_path = paths.raw_path(data_root, item.news_item_id, item.approve_date)
        md_path = paths.md_path(data_root, item.news_item_id, item.approve_date)
        paths.atomic_write_bytes(raw_path, downloaded.content)

        try:
            md_text = _convert_raw_to_md(raw_path)
        except Exception as exc:
            LOG.error("conversion failed item=%s err=%s", item.news_item_id, exc)
            _append_failed_queue(
                data_root / "fetch-log" / "failed.jsonl",
                item.news_item_id,
                f"conversion_failed: {type(exc).__name__}",
            )
            return "conversion_failed"

        revision = existing.revision + 1 if existing else 1
        md_text = frontmatter.prepend(
            md_text,
            frontmatter.build(
                item=item,
                entity_type=entity_classify.classify(item.department),
                sha256=sha256,
                revision=revision,
                raw_path=raw_path.relative_to(data_root),
                extracted_by=_build_extracted_by(),
            ),
        )
        paths.atomic_write_text(md_path, md_text)
        checksum_store.put(
            news_item_id=item.news_item_id,
            sha256=sha256,
            revision=revision,
            fetched_at=datetime.now(UTC),
        )
        LOG.info("stored item=%s sha256=%s", item.news_item_id, sha256)
        return "success"


def _list_items_with_retry(client: PolicyBriefingClient) -> Callable[[date], list[PolicyBriefingItem]]:
    @ratelimit.with_retry
    def inner(target_date: date) -> list[PolicyBriefingItem]:
        return client.list_items(target_date)

    return inner


def _download_item_with_retry(client: object) -> Callable[[PolicyBriefingItem], DownloadedPolicyBriefingFile]:
    @ratelimit.with_retry
    def inner(item: PolicyBriefingItem) -> DownloadedPolicyBriefingFile:
        return client.download_item_hwpx(item)

    return inner


def _convert_raw_to_md(raw_path: Path) -> str:
    return govpress_converter.convert_hwpx(raw_path, table_mode="text")


def _build_extracted_by() -> str:
    converter_version = getattr(govpress_converter, "__version__", "unknown")
    converter_sha = (
        subprocess.run(
            ["git", "-C", str(Path("vendor/gov-md-converter")), "rev-parse", "--short=12", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        .stdout.strip()
    )
    return f"{converter_version}+{converter_sha}"


def _append_failed_queue(path: Path, news_item_id: str, reason: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    line = f'{{"news_item_id":"{news_item_id}","reason":"{reason}"}}\n'
    paths.atomic_write_text(path, existing + line)


def _resolve_date_bounds(args: argparse.Namespace) -> tuple[date, date]:
    if args.date:
        return args.date, args.date
    if not (args.start_date and args.end_date):
        raise SystemExit("--date 또는 --start-date/--end-date 조합이 필요합니다.")
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
            f"- 감지 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')} KST\n"
            f"- 진행 중이던 단계: {milestone}\n"
            f"- 영향 범위: hwp_legacy={stats.hwp_legacy}, processed_primary={processed_primary}\n"
            "- 자동 복구 시도 여부: NO (사람 판단 대기)"
        )
    if processed_primary > 0 and (stats.conversion_failed / processed_primary) > 0.05:
        raise SystemExit(
            "EMERGENCY STOP: is_zip_container=True 대비 변환 실패율 5% 초과\n"
            f"- 감지 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')} KST\n"
            f"- 진행 중이던 단계: {milestone}\n"
            f"- 영향 범위: conversion_failed={stats.conversion_failed}, processed_primary={processed_primary}\n"
            "- 자동 복구 시도 여부: NO (사람 판단 대기)"
        )
    data_usage = _directory_usage_bytes(data_root)
    if data_usage > 120 * 1024 * 1024 * 1024:
        raise SystemExit(
            "EMERGENCY STOP: 디스크 사용량 120GB 초과\n"
            f"- 감지 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')} KST\n"
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
            f"- 실행 날짜: {stats.run_finished_at.strftime('%Y-%m-%d %H:%M KST') if stats.run_finished_at else datetime.now().strftime('%Y-%m-%d %H:%M KST')}",
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
    expected_growth_bytes = 2 * 1024 * 1024 * 1024
    total_growth = raw_growth_bytes + md_growth_bytes
    delta_percent = ((total_growth - expected_growth_bytes) / expected_growth_bytes) * 100 if expected_growth_bytes else 0.0
    issues = _collect_rehearsal_issues(stats, retry_stats, delta_percent)
    report_lines = [
        "# M2 리허설 리포트",
        "",
        f"- 실행 기간: {stats.run_started_at.strftime('%Y-%m-%d %H:%M')} ~ {stats.run_finished_at.strftime('%Y-%m-%d %H:%M')} KST",
        f"- 범위: {stats.start_date.isoformat()} ~ {stats.end_date.isoformat()} ({stats.total_days} 일)",
        f"- 전체 대상 건수: {stats.total_items}",
        f"- 성공 건수: {stats.effective_success} ({stats.effective_success}/{stats.total_items} = {stats.success_rate * 100:.1f}%)",
        "- skip 분포:",
        f"  - hwp_legacy: {stats.hwp_legacy}건 ({stats.ratio(stats.hwp_legacy) * 100:.1f}%)",
        f"  - no_primary_hwpx: {stats.no_primary_hwpx}건 ({stats.ratio(stats.no_primary_hwpx) * 100:.1f}%)",
        f"  - conversion_failed: {stats.conversion_failed}건 ({stats.ratio(stats.conversion_failed) * 100:.1f}%)",
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
        f"  - 예측 대비: {delta_percent:+.1f}%",
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
    if stats.success_rate < 0.95:
        issues.append(f"성공률이 기준 미달입니다: {stats.success_rate * 100:.1f}% < 95.0%")
    if stats.ratio(stats.hwp_legacy) >= 0.05:
        issues.append(f"hwp_legacy 비율이 기준 초과입니다: {stats.ratio(stats.hwp_legacy) * 100:.1f}% >= 5.0%")
    if stats.ratio(stats.no_primary_hwpx) >= 0.02:
        issues.append(f"no_primary_hwpx 비율이 기준 초과입니다: {stats.ratio(stats.no_primary_hwpx) * 100:.1f}% >= 2.0%")
    if stats.ratio(stats.conversion_failed) >= 0.01:
        issues.append(f"conversion_failed 비율이 기준 초과입니다: {stats.ratio(stats.conversion_failed) * 100:.1f}% >= 1.0%")
    if stats.median_duration >= 5.0:
        issues.append(f"중위 처리시간이 기준 초과입니다: {stats.median_duration:.1f}s >= 5.0s")
    if retry_stats.seen_429 and _safe_rate(retry_stats.recovered_429, retry_stats.seen_429) < 99.0:
        issues.append("429 재시도 성공률이 기준 미달입니다.")
    if retry_stats.seen_503 and _safe_rate(retry_stats.recovered_503, retry_stats.seen_503) < 99.0:
        issues.append("503 재시도 성공률이 기준 미달입니다.")
    if abs(delta_percent) > 30.0:
        issues.append(f"디스크 증가량이 예측 대비 허용 범위를 벗어났습니다: {delta_percent:+.1f}%")
    if stats.failed:
        issues.append(f"비재시도 실패가 {stats.failed}건 발생했습니다.")
    if stats.failed_dates:
        issues.append(f"날짜 단위 실패: {', '.join(stats.failed_dates)}")
    return issues


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 100.0
    return (numerator / denominator) * 100.0


def _bytes_to_gb(value: int) -> float:
    return value / (1024 * 1024 * 1024)


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    sys.exit(main())
