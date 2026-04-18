from __future__ import annotations

from pathlib import Path
from typing import Any

from govpress_mcp.paths import approve_datetime


def build(
    item: Any,
    entity_type: str,
    sha256: str,
    revision: int,
    raw_path: str | Path,
    extracted_by: str,
) -> dict[str, object]:
    approved_at = approve_datetime(item.approve_date).isoformat()
    normalized_raw_path = Path(raw_path).as_posix()
    if not normalized_raw_path.startswith("data/"):
        normalized_raw_path = f"data/{normalized_raw_path}"
    return {
        "id": str(item.news_item_id),
        "title": item.title,
        "department": item.department,
        "approve_date": approved_at,
        "entity_type": entity_type,
        "original_url": item.original_url,
        "sha256": sha256,
        "revision": revision,
        "extracted_by": extracted_by,
        "raw_path": normalized_raw_path,
    }


def prepend(md_text: str, frontmatter: dict[str, object]) -> str:
    lines = ["---"]
    for key, value in frontmatter.items():
        lines.append(f"{key}: {_serialize_scalar(value)}")
    lines.extend(["---", "", md_text.rstrip(), ""])
    return "\n".join(lines)


def parse(document: str) -> tuple[dict[str, str], str]:
    if not document.startswith("---\n"):
        raise ValueError("frontmatter 시작 구분자가 없습니다.")
    parts = document.split("\n---\n", 1)
    if len(parts) != 2:
        raise ValueError("frontmatter 종료 구분자가 없습니다.")
    header_block = parts[0][4:]
    body = parts[1].lstrip("\n")
    parsed: dict[str, str] = {}
    for line in header_block.splitlines():
        if not line.strip():
            continue
        key, value = line.split(": ", 1)
        parsed[key] = _deserialize_scalar(value)
    return parsed, body


def _serialize_scalar(value: object) -> str:
    if isinstance(value, int):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace("'", "''")
    return f"'{text}'"


def _deserialize_scalar(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("'") and stripped.endswith("'"):
        inner = stripped[1:-1]
        return inner.replace("''", "'").replace("\\\\", "\\")
    return stripped
