from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path


def ensure_dirs(data_root: Path) -> None:
    assert_supported_data_root(data_root)
    for relative in ("raw", "md", "fetch-log"):
        (data_root / relative).mkdir(parents=True, exist_ok=True)


def assert_supported_data_root(data_root: Path) -> None:
    resolved = data_root.expanduser().resolve()
    if str(resolved).startswith("/mnt/c/"):
        raise RuntimeError(f"/mnt/c 경로에는 데이터를 기록할 수 없습니다: {resolved}")


def approve_datetime(approve_date: str) -> datetime:
    return datetime.strptime(approve_date, "%m/%d/%Y %H:%M:%S")


def raw_path(data_root: Path, news_item_id: str, approve_date: str) -> Path:
    approved_at = approve_datetime(approve_date)
    return data_root / "raw" / approved_at.strftime("%Y") / approved_at.strftime("%m") / f"{news_item_id}.hwpx"


def md_path(data_root: Path, news_item_id: str, approve_date: str) -> Path:
    approved_at = approve_datetime(approve_date)
    return data_root / "md" / approved_at.strftime("%Y") / approved_at.strftime("%m") / f"{news_item_id}.md"


def atomic_write_bytes(target: Path, content: bytes) -> None:
    _atomic_write(target, content, mode="wb")


def atomic_write_text(target: Path, content: str) -> None:
    _atomic_write(target, content, mode="w", encoding="utf-8")


def _atomic_write(target: Path, content: bytes | str, *, mode: str, encoding: str | None = None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode=mode,
        encoding=encoding,
        dir=target.parent,
        prefix=f".{target.name}.",
        delete=False,
    ) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        tmp_name = handle.name
    Path(tmp_name).replace(target)
