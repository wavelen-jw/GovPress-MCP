from govpress_mcp.entity_classify import classify


def test_classify_departments() -> None:
    cases = {
        "과학기술정보통신부": "central",
        "기획재정부": "central",
        "행정안전부": "central",
        "질병관리청": "central",
        "서울특별시": "metro",
        "경기도": "metro",
        "부산광역시": "metro",
        "세종특별자치시": "metro",
        "수원시": "unknown",
        "강남구": "unknown",
    }
    for department, expected in cases.items():
        assert classify(department) == expected
