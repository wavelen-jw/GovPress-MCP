"""Execute expanded backfill manifests without calling the listing API."""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

from govpress_mcp import checksums, entity_classify, frontmatter, paths, ratelimit
from govpress_mcp.bulk_ingest import _convert_raw_to_md, _converter_metadata
from govpress_mcp.vendored.policy_briefing import REQUEST_USER_AGENT


DOWNLOAD_ACTIONS = {"download_hwpx", "download_pdf", "download_hwp"}
RESUME_STATUSES = {"success", "hwp_downloaded", "skip_sha", "dry_run"}
SOURCE_FORMAT_BY_ACTION = {
    "api_text_only": "api_text",
    "download_hwpx": "hwpx",
    "download_pdf": "pdf",
    "download_hwp": "hwp",
}
_HWP_QUEUE_LOCK = threading.Lock()
_LOG_LOCK = threading.Lock()
_HWP_QUEUE_IDS_BY_PATH: dict[Path, set[str]] = {}


def parse_date_range(value: str | None) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    start, sep, end = value.partition("..")
    if sep != ".." or not start or not end:
        raise SystemExit("--date-range 형식은 YYYY-MM-DD..YYYY-MM-DD 이어야 합니다.")
    return start, end


def iter_manifest(path: Path, *, date_range: tuple[str | None, str | None], sample: int | None) -> Iterable[dict[str, Any]]:
    start, end = date_range
    yielded = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            target_date = str(row.get("target_date") or "")
            if start is not None and target_date < start:
                continue
            if end is not None and target_date > end:
                continue
            yield row
            yielded += 1
            if sample is not None and yielded >= sample:
                return


def item_from_row(row: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        news_item_id=str(row["news_item_id"]),
        title=row.get("title") or "",
        department=row.get("department") or "",
        approve_date=row.get("approve_date") or "",
        original_url=row.get("original_url") or "",
    )


def api_text_markdown(row: dict[str, Any]) -> str:
    title = (row.get("title") or "").strip()
    body = (row.get("data_contents_text") or "").strip()
    if title and not body.startswith(title):
        return f"# {title}\n\n{body}\n"
    return f"{body}\n"


def write_api_text(
    row: dict[str, Any],
    *,
    data_root: Path,
    checksum_store: checksums.Store,
    dry_run: bool,
) -> str:
    item = item_from_row(row)
    body = api_text_markdown(row)
    content_for_hash = (row.get("data_contents_html") or body).encode("utf-8")
    sha256 = hashlib.sha256(content_for_hash).hexdigest()
    md_path = paths.md_path(data_root, item.news_item_id, item.approve_date)
    existing = checksum_store.get(item.news_item_id)
    if existing and existing.sha256 == sha256 and existing.source_format == "api_text" and md_path.exists():
        return "skip_sha"
    if dry_run:
        return "dry_run"

    revision = existing.revision + 1 if existing else 1
    metadata = frontmatter.build(
        item=item,
        entity_type=entity_classify.classify(item.department),
        sha256=sha256,
        revision=revision,
        raw_path=Path("api_text") / f"{item.news_item_id}.html",
        govpress_version="api_text",
        govpress_commit=_git_commit(),
        source_format="api_text",
    )
    paths.atomic_write_text(md_path, frontmatter.prepend(body, metadata))
    checksum_store.put(
        news_item_id=item.news_item_id,
        sha256=sha256,
        revision=revision,
        fetched_at=datetime.now(UTC),
        govpress_version="api_text",
        govpress_commit=_git_commit(),
        source_format="api_text",
    )
    return "success"


def _git_commit() -> str:
    # Keep api_text provenance distinct from govpress-converter versions.
    try:
        import subprocess

        return subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


@ratelimit.with_retry
def download_bytes(url: str, referer: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": REQUEST_USER_AGENT,
            "Referer": referer or "https://www.korea.kr/",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def process_download(
    row: dict[str, Any],
    *,
    data_root: Path,
    checksum_store: checksums.Store,
    dry_run: bool,
    hwp_queue: Path,
) -> str:
    item = item_from_row(row)
    action = str(row["action"])
    source_format = SOURCE_FORMAT_BY_ACTION[action]
    attachment = row.get("attachment") or {}
    file_url = attachment.get("file_url")
    if not file_url:
        return "missing_attachment"
    if dry_run:
        return "dry_run"

    ratelimit_sync_sleep()
    content = download_bytes(str(file_url), item.original_url)
    sha256 = hashlib.sha256(content).hexdigest()
    existing = checksum_store.get(item.news_item_id)
    raw_path = paths.raw_path(data_root, item.news_item_id, item.approve_date, source_format=source_format)
    md_path = paths.md_path(data_root, item.news_item_id, item.approve_date)
    if existing and existing.sha256 == sha256 and existing.source_format == source_format:
        if source_format == "hwp" and raw_path.exists():
            append_hwp_queue_once(
                hwp_queue,
                item=item,
                raw_path=raw_path,
                data_root=data_root,
                reason="expanded_backfill_hwp_existing_raw",
            )
            return "skip_sha"
        if md_path.exists():
            return "skip_sha"

    paths.atomic_write_bytes(raw_path, content)
    revision = existing.revision + 1 if existing else 1

    if source_format == "hwp":
        checksum_store.put(
            news_item_id=item.news_item_id,
            sha256=sha256,
            revision=revision,
            fetched_at=datetime.now(UTC),
            source_format="hwp",
        )
        append_hwp_queue_once(
            hwp_queue,
            item=item,
            raw_path=raw_path,
            data_root=data_root,
            reason="expanded_backfill_hwp",
        )
        return "hwp_downloaded"

    try:
        md_body = _convert_raw_to_md(raw_path, source_format=source_format)
    except Exception as exc:
        append_jsonl(
            data_root / "fetch-log" / "failed.jsonl",
            {
                "news_item_id": item.news_item_id,
                "reason": f"conversion_failed: {type(exc).__name__}: {exc}",
            },
        )
        return "conversion_failed"

    govpress_version, govpress_commit = _converter_metadata()
    metadata = frontmatter.build(
        item=item,
        entity_type=entity_classify.classify(item.department),
        sha256=sha256,
        revision=revision,
        raw_path=raw_path.relative_to(data_root),
        govpress_version=govpress_version,
        govpress_commit=govpress_commit,
        source_format=source_format,
    )
    paths.atomic_write_text(md_path, frontmatter.prepend(md_body, metadata))
    checksum_store.put(
        news_item_id=item.news_item_id,
        sha256=sha256,
        revision=revision,
        fetched_at=datetime.now(UTC),
        govpress_version=govpress_version,
        govpress_commit=govpress_commit,
        source_format=source_format,
    )
    return "success"


def ratelimit_sync_sleep() -> None:
    time.sleep(ratelimit.MIN_INTERVAL_SECONDS)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with _LOG_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def append_hwp_queue_once(
    path: Path,
    *,
    item: SimpleNamespace,
    raw_path: Path,
    data_root: Path,
    reason: str,
) -> None:
    with _HWP_QUEUE_LOCK:
        queue_path = path.resolve()
        queued_ids = _HWP_QUEUE_IDS_BY_PATH.get(queue_path)
        if queued_ids is None:
            queued_ids = set()
            _HWP_QUEUE_IDS_BY_PATH[queue_path] = queued_ids
        if not queued_ids and path.exists():
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        news_item_id = json.loads(line).get("news_item_id")
                    except json.JSONDecodeError:
                        continue
                    if news_item_id:
                        queued_ids.add(str(news_item_id))
        if item.news_item_id in queued_ids:
            return
        append_jsonl(
            path,
            {
                "news_item_id": item.news_item_id,
                "approve_date": paths.approve_datetime(item.approve_date).date().isoformat(),
                "reason": reason,
                "hwp_path": raw_path.relative_to(data_root).as_posix(),
            },
        )
        queued_ids.add(item.news_item_id)


def load_completed_items(path: Path) -> set[tuple[str, str]]:
    completed: set[tuple[str, str]] = set()
    if not path.exists():
        return completed
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("event") != "item":
                continue
            if row.get("status") not in RESUME_STATUSES:
                continue
            news_item_id = row.get("news_item_id")
            action = row.get("action")
            if news_item_id and action:
                completed.add((str(action), str(news_item_id)))
    return completed


def _log_item(log_json: Path, manifest: Path, row: dict[str, Any], action: str, status: str) -> None:
    append_jsonl(
        log_json,
        {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": "item",
            "manifest": manifest.as_posix(),
            "news_item_id": row.get("news_item_id"),
            "target_date": row.get("target_date"),
            "action": action,
            "status": status,
        },
    )


def process_manifest(
    manifest: Path,
    *,
    data_root: Path,
    checksum_store: checksums.Store,
    date_range: tuple[str | None, str | None],
    sample: int | None,
    dry_run: bool,
    log_json: Path,
    hwp_queue: Path,
    completed_items: set[tuple[str, str]],
    concurrency: int,
) -> Counter[str]:
    counts: Counter[str] = Counter()
    rows = list(iter_manifest(manifest, date_range=date_range, sample=sample))

    def process_row(row: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
        action = str(row["action"])
        news_item_id = str(row.get("news_item_id"))
        if (action, news_item_id) in completed_items:
            return row, action, "resume_skip"
        try:
            if action == "api_text_only":
                status = write_api_text(row, data_root=data_root, checksum_store=checksum_store, dry_run=dry_run)
            elif action in DOWNLOAD_ACTIONS:
                status = process_download(
                    row,
                    data_root=data_root,
                    checksum_store=checksum_store,
                    dry_run=dry_run,
                    hwp_queue=hwp_queue,
                )
            else:
                status = "skipped_action"
        except Exception as exc:
            status = "failed"
            append_jsonl(
                log_json,
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "event": "item_error",
                    "manifest": manifest.as_posix(),
                    "news_item_id": row.get("news_item_id"),
                    "action": action,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
        return row, action, status

    if concurrency > 1 and any(str(row.get("action")) in DOWNLOAD_ACTIONS for row in rows):
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(process_row, row) for row in rows]
            for future in as_completed(futures):
                row, action, status = future.result()
                counts[status] += 1
                _log_item(log_json, manifest, row, action, status)
    else:
        for row in rows:
            row, action, status = process_row(row)
            counts[status] += 1
            _log_item(log_json, manifest, row, action, status)
    return counts


def resolve_manifests(args: argparse.Namespace) -> list[Path]:
    if args.manifest:
        return args.manifest
    names: list[str] = []
    actions = set(args.actions.split(","))
    if "api_text_only" in actions:
        names.append("manifest-api-text.jsonl")
    if "download_hwpx" in actions:
        names.append("manifest-hwpx.jsonl")
    if "download_pdf" in actions:
        names.append("manifest-pdf.jsonl")
    if "download_hwp" in actions:
        for year in range(args.hwp_year_from, args.hwp_year_to + 1):
            names.append(f"manifest-hwp-{year}.jsonl")
    return [args.manifest_dir / name for name in names if (args.manifest_dir / name).exists()]


def run(args: argparse.Namespace) -> int:
    data_root = args.data_root.expanduser().resolve()
    paths.assert_supported_data_root(data_root)
    date_range = parse_date_range(args.date_range)
    manifests = resolve_manifests(args)
    if not manifests:
        raise SystemExit("처리할 manifest가 없습니다.")
    checksum_store = checksums.open_store(data_root / "fetch-log" / "checksums.db")
    completed_items = load_completed_items(args.log_json) if args.resume else set()
    totals: Counter[str] = Counter()
    for manifest in manifests:
        counts = process_manifest(
            manifest,
            data_root=data_root,
            checksum_store=checksum_store,
            date_range=date_range,
            sample=args.sample,
            dry_run=args.dry_run,
            log_json=args.log_json,
            hwp_queue=args.hwp_queue,
            completed_items=completed_items,
            concurrency=args.concurrency,
        )
        totals.update(counts)
        append_jsonl(
            args.log_json,
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "event": "manifest_summary",
                "manifest": manifest.as_posix(),
                "counts": dict(counts),
            },
        )
    checksum_store.close()
    append_jsonl(args.log_json, {"timestamp": datetime.now(UTC).isoformat(), "event": "run_summary", "counts": dict(totals)})
    print(f"manifest run complete counts={dict(totals)} log={args.log_json}", flush=True)
    return 0 if totals.get("failed", 0) == 0 else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run expanded backfill manifests.")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--manifest-dir", type=Path, default=Path("data/fetch-log"))
    parser.add_argument("--manifest", type=Path, action="append")
    parser.add_argument("--actions", default="api_text_only,download_hwpx,download_pdf,download_hwp")
    parser.add_argument("--date-range", help="YYYY-MM-DD..YYYY-MM-DD")
    parser.add_argument("--hwp-year-from", type=int, default=1999)
    parser.add_argument("--hwp-year-to", type=int, default=2026)
    parser.add_argument("--sample", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--log-json", type=Path, default=Path("data/fetch-log/expanded-backfill.jsonl"))
    parser.add_argument("--hwp-queue", type=Path, default=Path("data/fetch-log/hwp-queue-expanded.jsonl"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.sample is not None and args.sample < 1:
        raise SystemExit("--sample은 1 이상이어야 합니다.")
    if args.concurrency < 1:
        raise SystemExit("--concurrency는 1 이상이어야 합니다.")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
