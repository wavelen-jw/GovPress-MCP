from types import SimpleNamespace

from govpress_mcp import frontmatter


def test_frontmatter_round_trip() -> None:
    item = SimpleNamespace(
        news_item_id="123",
        title="테스트 제목",
        department="행정안전부",
        approve_date="04/10/2026 06:00:00",
        original_url="https://www.korea.kr/example",
    )
    fm = frontmatter.build(
        item=item,
        entity_type="central",
        sha256="abc123",
        revision=1,
        raw_path="data/raw/2026/04/123.hwpx",
        govpress_version="0.1.9",
        govpress_commit="85cb2e8f57ce",
        source_format="hwpx",
    )

    document = frontmatter.prepend("# 본문", fm)
    parsed, body = frontmatter.parse(document)

    assert set(parsed) == {
        "id",
        "title",
        "department",
        "approve_date",
        "entity_type",
        "original_url",
        "sha256",
        "revision",
        "govpress_version",
        "govpress_commit",
        "source_format",
        "raw_path",
    }
    assert parsed["approve_date"] == "2026-04-10T06:00:00"
    assert parsed["revision"] == "1"
    assert parsed["govpress_version"] == "0.1.9"
    assert parsed["govpress_commit"] == "85cb2e8f57ce"
    assert parsed["source_format"] == "hwpx"
    assert body == "# 본문\n"


def test_parse_multiline_frontmatter_value() -> None:
    document = """---
id: '156747571'
title: As the new semester begins, the use of smart devices in schools is legally
  restricted
department: 법제처
approve_date: '2026-03-06T09:43:30'
entity_type: central
original_url: 'https://example.com'
sha256: 'abc'
revision: 1
govpress_version: 0.1.9
govpress_commit: 85cb2e8f57ce
source_format: hwpx
raw_path: data/raw/2026/03/156747571.hwpx
---

본문
"""
    parsed, body = frontmatter.parse(document)

    assert parsed["title"] == (
        "As the new semester begins, the use of smart devices in schools is legally restricted"
    )
    assert parsed["department"] == "법제처"
    assert body == "본문\n"
