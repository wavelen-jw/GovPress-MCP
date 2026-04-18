"""
Govpress MCP — bulk ingestion entry point.

반드시 AGENTS.md를 먼저 읽어라. 이 파일은 골격만 제공한다.
TODO 마커가 달린 곳을 채우면서 AGENTS.md §4의 탈출 조건을 하나씩 체크하라.

실행 예시:
    # 단일 날짜
    python -m govpress_mcp.bulk_ingest --date 2026-04-10 --limit 10

    # 날짜 범위 (백필)
    python -m govpress_mcp.bulk_ingest --start-date 2024-01-01 --end-date 2024-01-31
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator

import govpress_converter  # editable install from vendor/gov-md-converter
from govpress_mcp.vendored.policy_briefing import (  # vendored copy
    DownloadedPolicyBriefingFile,
    PolicyBriefingClient,
    PolicyBriefingItem,
)
from govpress_mcp import checksums, entity_classify, frontmatter, paths, ratelimit

LOG = logging.getLogger("govpress_mcp.bulk_ingest")

# AGENTS.md §1.3 — 이 도메인으로 나가는 요청은 금지.
FORBIDDEN_HOSTS = ("api2.govpress.cloud",)


# =============================================================================
# CLI
# =============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Govpress MCP bulk ingestion")
    parser.add_argument("--date", type=_parse_iso_date, help="단일 날짜 (YYYY-MM-DD)")
    parser.add_argument("--start-date", type=_parse_iso_date, help="백필 시작일 (포함)")
    parser.add_argument("--end-date", type=_parse_iso_date, help="백필 종료일 (포함)")
    parser.add_argument("--limit", type=int, default=None, help="최대 처리 건수 (디버깅용)")
    parser.add_argument("--dry-run", action="store_true", help="다운로드·저장 없이 list만")
    parser.add_argument("--data-root", type=Path, default=Path("/home/USER/govpress-mcp/data"),
                        help="AGENTS.md §1.6 저장 루트. 운영 시 실제 USER로 치환.")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def _parse_iso_date(text: str) -> date:
    return datetime.strptime(text, "%Y-%m-%d").date()


# =============================================================================
# 메인 파이프라인
# =============================================================================

async def run(args: argparse.Namespace) -> int:
    _setup_logging(args.log_level)
    _assert_env()

    client = PolicyBriefingClient(
        service_key=os.environ["GOVPRESS_POLICY_BRIEFING_SERVICE_KEY"],
        timeout_seconds=8,
    )
    paths.ensure_dirs(args.data_root)
    checksum_store = checksums.open_store(args.data_root / "fetch-log" / "checksums.db")

    total = 0
    warmed = 0
    skipped = 0
    failed = 0

    semaphore = asyncio.Semaphore(5)  # AGENTS.md §1.9

    for target_date in _iter_dates(args):
        LOG.info("fetching date=%s", target_date.isoformat())
        try:
            items = client.list_items(target_date)
        except Exception as exc:  # TODO: 세분화된 예외 처리
            LOG.error("list_items failed date=%s err=%s", target_date, exc)
            failed += 1
            continue

        processed_today = 0
        tasks = []
        for item in items:
            if item.primary_hwpx is None:
                continue
            if args.limit is not None and (warmed + skipped) >= args.limit:
                break
            tasks.append(_process_one(
                client=client,
                item=item,
                target_date=target_date,
                data_root=args.data_root,
                checksum_store=checksum_store,
                semaphore=semaphore,
                dry_run=args.dry_run,
            ))
            processed_today += 1

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            total += 1
            if isinstance(result, Exception):
                failed += 1
                LOG.exception("item failed: %s", result)
            elif result == "skipped":
                skipped += 1
            else:
                warmed += 1

    LOG.info("done total=%d warmed=%d skipped=%d failed=%d", total, warmed, skipped, failed)
    return 0 if failed == 0 else 2


async def _process_one(
    *,
    client: PolicyBriefingClient,
    item: PolicyBriefingItem,
    target_date: date,
    data_root: Path,
    checksum_store: checksums.Store,
    semaphore: asyncio.Semaphore,
    dry_run: bool,
) -> str:
    """
    단일 item 처리:
      1. sha256 사전 체크 (기존 == 새 원본이면 skip)
      2. 다운로드
      3. HWPX 저장 (data/raw/...)
      4. convert_hwpx → MD
      5. frontmatter 주입 → data/md/... 저장
      6. checksum 기록

    반환값: "warmed" | "skipped"
    """
    async with semaphore:
        await ratelimit.throttle()  # AGENTS.md §1.9: 0.3s 간격

        if dry_run:
            LOG.info("dry_run item=%s title=%s", item.news_item_id, item.title[:40])
            return "skipped"

        # TODO: 사전 sha256 체크를 위해 HEAD 요청 또는 다운로드 후 비교 전략 결정.
        # korea.kr 첨부 URL은 HEAD 신뢰도가 낮으므로 일단 다운로드 → 비교가 안전.

        try:
            downloaded: DownloadedPolicyBriefingFile = client.download_item_hwpx(item)
        except ratelimit.RetryableError:
            raise
        except Exception as exc:
            LOG.warning("download failed item=%s err=%s", item.news_item_id, exc)
            raise

        if not downloaded.is_zip_container:
            LOG.info("not-hwpx-binary item=%s file=%s", item.news_item_id, downloaded.attachment.file_name)
            return "skipped"

        new_sha = hashlib.sha256(downloaded.content).hexdigest()
        existing = checksum_store.get(item.news_item_id)
        if existing and existing.sha256 == new_sha:
            LOG.info("skip-unchanged item=%s sha256=%s", item.news_item_id, new_sha[:12])
            return "skipped"

        raw_path = paths.raw_path(data_root, item, target_date)
        paths.atomic_write_bytes(raw_path, downloaded.content)

        md_text = await _convert(downloaded, raw_path)

        fm = frontmatter.build(
            item=item,
            entity_type=entity_classify.classify(item.department),
            sha256=new_sha,
            revision=(existing.revision + 1) if existing else 1,
            raw_path=raw_path.relative_to(data_root),
        )
        md_final = frontmatter.prepend(md_text, fm)

        md_path = paths.md_path(data_root, item, target_date)
        paths.atomic_write_text(md_path, md_final)

        checksum_store.put(
            news_item_id=item.news_item_id,
            sha256=new_sha,
            revision=fm["revision"],
            fetched_at=datetime.utcnow(),
        )
        LOG.info("warmed item=%s sha256=%s", item.news_item_id, new_sha[:12])
        return "warmed"


async def _convert(downloaded: DownloadedPolicyBriefingFile, raw_path: Path) -> str:
    """
    govpress_converter.convert_hwpx는 파일 경로를 요구하므로 임시 파일에 쓰거나
    이미 저장된 raw_path를 그대로 사용한다.

    TODO: table_mode="text" / "html" 중 어느 쪽을 저장할지 결정. AGENTS.md §1.7
    frontmatter에는 text 버전을 쓰고, html은 필요 시 derive_hot.py에서 재변환.
    """
    # raw_path에 이미 저장된 상태라는 전제
    return await asyncio.to_thread(
        govpress_converter.convert_hwpx,
        str(raw_path),
        table_mode="text",
    )


# =============================================================================
# 날짜 이터레이터
# =============================================================================

def _iter_dates(args: argparse.Namespace) -> Iterator[date]:
    if args.date:
        yield args.date
        return
    if not (args.start_date and args.end_date):
        raise SystemExit("--date 또는 --start-date/--end-date 중 하나는 필요")
    current = args.start_date
    while current <= args.end_date:
        yield current
        current += timedelta(days=1)


# =============================================================================
# 환경 검증
# =============================================================================

def _assert_env() -> None:
    if not os.environ.get("GOVPRESS_POLICY_BRIEFING_SERVICE_KEY"):
        raise SystemExit("GOVPRESS_POLICY_BRIEFING_SERVICE_KEY 환경변수가 없음. .env 확인.")
    # TODO: HTTP 클라이언트에 FORBIDDEN_HOSTS 차단 훅 추가 (requests/httpx adapter).


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


# =============================================================================

def main() -> int:
    args = parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
