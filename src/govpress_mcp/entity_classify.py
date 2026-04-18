from __future__ import annotations

METRO_PREFIXES = {
    "서울특별시",
    "부산광역시",
    "대구광역시",
    "인천광역시",
    "광주광역시",
    "대전광역시",
    "울산광역시",
    "세종특별자치시",
    "경기도",
    "강원특별자치도",
    "충청북도",
    "충청남도",
    "전북특별자치도",
    "전라남도",
    "경상북도",
    "경상남도",
    "제주특별자치도",
}

CENTRAL_SUFFIXES = ("부", "처", "청", "위원회")
CENTRAL_EXACT = {
    "국무조정실",
    "국가보훈부",
    "검찰청",
    "경찰청",
    "관세청",
    "국세청",
    "기상청",
    "기획재정부",
    "농림축산식품부",
    "병무청",
    "산림청",
    "소방청",
    "식품의약품안전처",
    "외교부",
    "조달청",
    "질병관리청",
    "통계청",
    "특허청",
    "해양경찰청",
    "행정안전부",
    "환경부",
}


def classify(department: str) -> str:
    normalized = (department or "").strip()
    if not normalized:
        return "unknown"
    if normalized in METRO_PREFIXES:
        return "metro"
    if normalized in CENTRAL_EXACT:
        return "central"
    if normalized.endswith(CENTRAL_SUFFIXES):
        return "central"
    return "unknown"
