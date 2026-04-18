"""Stamp existing MD files and checksums.db with govpress_version + govpress_commit + source_format.

One-time backfill utility for the M1 -> M2 -> M3 frontmatter schema migration (v2).

Before this change, MDs carried a single composite field:
    extracted_by: "<version>+<commit>"

After this change (AGENTS.md §1.7 v2), MDs carry three explicit fields:
    govpress_version: "<semver>"
    govpress_commit:  "<short git sha>"
    source_format:    "hwpx"   # existing MDs are HWPX-derived

This utility:
  1. Parses extracted_by from every MD under data/md/**/*.md
  2. Writes govpress_version + govpress_commit + source_format (default "hwpx")
  3. Removes the composite extracted_by field
  4. ALTER TABLE checksums.db to add govpress_version / govpress_commit / source_format columns
  5. UPDATEs existing rows from parsed values (source_format = 'hwpx' for all existing rows)

Idempotent. Re-running is safe:
  - MDs already in the new format (have govpress_version + source_format) are skipped.
  - ALTER TABLE with duplicate column is caught and ignored.

Usage::

    python -m govpress_mcp.stamp_version [--data-root PATH] [--dry-run] [--verbose]

Exit codes:
    0  success (including dry-run)
    1  one or more MDs could not be parsed (missing BOTH old and new fields)
    2  unexpected fatal error

Emits a summary line to stdout suitable for piping into commit messages.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

try:
    import yaml  # PyYAML
except ImportError as e:  # pragma: no cover
    print("[FATAL] PyYAML가 필요합니다. `pip install pyyaml`", file=sys.stderr)
    raise SystemExit(2) from e


FRONTMATTER_DELIM = "---"
DEFAULT_SOURCE_FORMAT = "hwpx"  # 기존 MD는 모두 HWPX 변환본


@dataclass
class StampResult:
    scanned: int = 0
    already_new: int = 0
    migrated: int = 0
    source_format_added: int = 0   # govpress_version은 있었지만 source_format이 없던 건
    unparseable: int = 0
    db_rows_updated: int = 0
    db_columns_added: int = 0


def iter_md_files(data_root: Path) -> Iterator[Path]:
    md_root = data_root / "md"
    if not md_root.is_dir():
        return
    yield from sorted(md_root.rglob("*.md"))


def split_frontmatter(text: str) -> tuple[dict, str] | None:
    """Return (frontmatter_dict, body) or None if no frontmatter block."""
    if not text.startswith(FRONTMATTER_DELIM):
        return None
    lines = text.split("\n")
    if lines[0].strip() != FRONTMATTER_DELIM:
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == FRONTMATTER_DELIM:
            fm_text = "\n".join(lines[1:i])
            body = "\n".join(lines[i + 1:])
            try:
                data = yaml.safe_load(fm_text) or {}
            except yaml.YAMLError:
                return None
            if not isinstance(data, dict):
                return None
            return data, body
    return None


def serialize_frontmatter(fm: dict, body: str) -> str:
    dumped = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).rstrip()
    return f"{FRONTMATTER_DELIM}\n{dumped}\n{FRONTMATTER_DELIM}\n{body}"


def parse_extracted_by(value: str) -> tuple[str, str] | None:
    """Split '<version>+<commit>' into (version, commit). Returns None if malformed."""
    if not isinstance(value, str):
        return None
    if "+" not in value:
        return None
    version, _, commit = value.partition("+")
    version = version.strip()
    commit = commit.strip()
    if not version or not commit:
        return None
    return version, commit


def atomic_write_text(path: Path, text: str) -> None:
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def stamp_md_file(path: Path, dry_run: bool, verbose: bool) -> str:
    text = path.read_text(encoding="utf-8")
    parsed = split_frontmatter(text)
    if parsed is None:
        if verbose:
            print(f"  [unparseable] {path}: no valid frontmatter")
        return "unparseable"

    fm, body = parsed
    has_new_version = "govpress_version" in fm and "govpress_commit" in fm
    has_source_format = "source_format" in fm
    has_old = "extracted_by" in fm

    # 완전한 v2 형식 (govpress_version + govpress_commit + source_format, extracted_by 없음)
    if has_new_version and has_source_format and not has_old:
        return "already-new"

    # govpress_version 있는데 source_format만 없는 경우 (v1.5 중간 상태)
    if has_new_version and not has_source_format:
        if not has_old:
            # extracted_by도 없으면 source_format만 추가
            fm["source_format"] = DEFAULT_SOURCE_FORMAT
            if verbose:
                print(f"  [source_format-add] {path}: added source_format=hwpx")
            if not dry_run:
                atomic_write_text(path, serialize_frontmatter(fm, body))
            return "source-format-added"
        # extracted_by도 있는 경우: 아래로 떨어져서 전체 마이그레이션

    # govpress_version이 있고 extracted_by도 있는 경우: extracted_by만 제거 (+ source_format 추가)
    if has_new_version and has_old:
        new_fm = {k: v for k, v in fm.items() if k != "extracted_by"}
        if not has_source_format:
            new_fm["source_format"] = DEFAULT_SOURCE_FORMAT
        if verbose:
            print(f"  [cleanup] {path}: drop extracted_by (+ source_format if missing)")
        if not dry_run:
            atomic_write_text(path, serialize_frontmatter(new_fm, body))
        return "migrated"

    # extracted_by가 없고 govpress_version도 없음 → 파싱 불가
    if not has_old:
        if verbose:
            print(f"  [unparseable] {path}: no extracted_by and no govpress_version")
        return "unparseable"

    # 주 경로: extracted_by → govpress_version + govpress_commit + source_format
    split = parse_extracted_by(fm["extracted_by"])
    if split is None:
        if verbose:
            print(f"  [unparseable] {path}: extracted_by={fm['extracted_by']!r}")
        return "unparseable"

    version, commit = split

    # 필드 순서: 기존 필드 보존 + extracted_by 자리에 3개 필드 삽입
    new_fm: dict = {}
    for k, v in fm.items():
        if k == "extracted_by":
            new_fm["govpress_version"] = version
            new_fm["govpress_commit"] = commit
            new_fm["source_format"] = DEFAULT_SOURCE_FORMAT
        else:
            new_fm[k] = v

    if verbose:
        print(f"  [migrate] {path}: v={version} commit={commit} source_format=hwpx")

    if not dry_run:
        atomic_write_text(path, serialize_frontmatter(new_fm, body))

    return "migrated"


def _has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == col for row in cur.fetchall())


def migrate_db(db_path: Path, dry_run: bool, verbose: bool) -> tuple[int, int]:
    if not db_path.exists():
        if verbose:
            print(f"  [skip-db] {db_path} not found")
        return 0, 0
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='checksums'"
        )
        if cur.fetchone() is None:
            if verbose:
                print(f"  [skip-db] no 'checksums' table in {db_path}")
            return 0, 0
        cols_added = 0
        for col in ("govpress_version", "govpress_commit", "source_format"):
            if not _has_column(conn, "checksums", col):
                if verbose:
                    print(f"  [db] ALTER TABLE checksums ADD COLUMN {col}")
                if not dry_run:
                    conn.execute(f"ALTER TABLE checksums ADD COLUMN {col} TEXT")
                cols_added += 1
        # source_format 기본값 채우기 (신규 컬럼이면 기존 행 NULL → 'hwpx')
        if not _has_column(conn, "checksums", "source_format") or dry_run:
            pass  # dry-run에서는 스킵
        else:
            res = conn.execute(
                "UPDATE checksums SET source_format = 'hwpx' WHERE source_format IS NULL"
            )
            if verbose and res.rowcount > 0:
                print(f"  [db] source_format=hwpx 기본값 설정: {res.rowcount}행")
        if not dry_run:
            conn.commit()
        return cols_added, 0
    finally:
        conn.close()


def populate_db(data_root: Path, db_path: Path, dry_run: bool, verbose: bool) -> int:
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='checksums'"
        )
        if cur.fetchone() is None:
            return 0
        if not _has_column(conn, "checksums", "govpress_version"):
            return 0
        updated = 0
        for md_path in iter_md_files(data_root):
            text = md_path.read_text(encoding="utf-8")
            parsed = split_frontmatter(text)
            if parsed is None:
                continue
            fm, _body = parsed
            item_id = fm.get("id")
            version = fm.get("govpress_version")
            commit = fm.get("govpress_commit")
            source_format = fm.get("source_format", DEFAULT_SOURCE_FORMAT)
            if not (item_id and version and commit):
                continue
            if dry_run:
                updated += 1
                continue
            res = conn.execute(
                "UPDATE checksums SET govpress_version = ?, govpress_commit = ?, source_format = ? "
                "WHERE news_item_id = ? "
                "AND (govpress_version IS NULL OR govpress_commit IS NULL "
                "     OR govpress_version != ? OR govpress_commit != ? OR source_format IS NULL)",
                (version, commit, source_format, item_id, version, commit),
            )
            updated += res.rowcount
        if not dry_run:
            conn.commit()
        return updated
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Stamp existing MDs and checksums.db with govpress_version, "
            "govpress_commit, and source_format fields. (v2 migration)"
        )
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path.home() / "govpress-mcp" / "data",
        help="Data root (contains md/ and fetch-log/). Default: ~/govpress-mcp/data",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report planned changes without writing anything.",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Per-file log.")
    args = parser.parse_args(argv)

    data_root: Path = args.data_root.expanduser().resolve()
    if not data_root.is_dir():
        print(f"[FATAL] data-root not found: {data_root}", file=sys.stderr)
        return 2

    result = StampResult()
    print(f"[stamp-version v2] data-root = {data_root}")
    if args.dry_run:
        print("[stamp-version v2] DRY-RUN — no files will be written")

    for md_path in iter_md_files(data_root):
        result.scanned += 1
        status = stamp_md_file(md_path, dry_run=args.dry_run, verbose=args.verbose)
        if status == "already-new":
            result.already_new += 1
        elif status == "migrated":
            result.migrated += 1
        elif status == "source-format-added":
            result.source_format_added += 1
        elif status == "unparseable":
            result.unparseable += 1

    db_path = data_root / "fetch-log" / "checksums.db"
    cols_added, _ = migrate_db(db_path, dry_run=args.dry_run, verbose=args.verbose)
    result.db_columns_added = cols_added
    result.db_rows_updated = populate_db(
        data_root, db_path, dry_run=args.dry_run, verbose=args.verbose
    )

    print()
    print("=" * 60)
    print(f"  MD scanned              : {result.scanned}")
    print(f"  already v2 format       : {result.already_new}")
    print(f"  migrated (v1 → v2)      : {result.migrated}")
    print(f"  source_format added     : {result.source_format_added}")
    print(f"  UNPARSEABLE             : {result.unparseable}")
    print(f"  DB columns added        : {result.db_columns_added}")
    print(f"  DB rows updated         : {result.db_rows_updated}")
    print("=" * 60)

    if result.unparseable > 0:
        print(
            f"[FAIL] {result.unparseable} MD(s) could not be migrated. "
            "Inspect with --verbose.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
