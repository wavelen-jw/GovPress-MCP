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
        extracted_by="0.1.9+85cb2e8f57ce",
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
        "extracted_by",
        "raw_path",
    }
    assert parsed["approve_date"] == "2026-04-10T06:00:00"
    assert parsed["revision"] == "1"
    assert body == "# 본문\n"
