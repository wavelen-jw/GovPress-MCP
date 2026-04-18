---
title: 보도자료 Silent Overwrite 검증 실험 계획
purpose: compare_versions 도구의 존속/제거 판단 근거 확보
decision_owner: 준우
date: 2026-04-17
status: 설계 단계 (T1 베이스라인 아직 수집 전)
---

# 보도자료 Silent Overwrite 검증 실험 계획

## 1. 왜 이 실험이 필요한가

`compare_versions` 도구는 기능 명세 §5의 전제에 크게 의존한다: **"동일 보도자료 ID의 본문이 시간이 지나면서 바뀔 수 있다"**. 이 전제가 약하다면 도구의 ROI가 급락한다.

현재 두 가지 가정이 연쇄적으로 걸려 있다.

1. 공식 "정정 보도자료" 빈도 → 거의 없음 (준우의 도메인 지식)
2. URL 덮어쓰기(silent overwrite) 빈도 → 사실상 없음 (가정, 미측정)

가정 2를 측정 없이 채택하고 도구를 제거하면, 나중에 "실제로는 연 수십 건 있었는데 놓쳤다"를 되돌리기 비용이 크다. 반대로 측정 없이 도구를 유지하면 기능 명세·README·데모가 실제로는 거의 트리거되지 않는 기능을 킬러 격으로 홍보하는 꼴이 된다.

**결정 함수**: 6개월 이상 추적 기간에서 silent overwrite가 전체 표본의 0.5% 이상이면 `compare_versions` 유지, 그 미만이면 제거.

## 2. 측정 대상 정의

"silent overwrite"를 다음과 같이 4계층으로 구분해 측정한다. 계층별로 실무적 가치가 다르다.

| 계층 | 변경 성격 | 실무적 가치 | 검출 방법 |
|---|---|---|---|
| L0 | 공백·문장부호·인코딩만 차이 | 없음 | 정규화 후 해시 비교 |
| L1 | 첨부파일 추가, 페이지 하단 메타데이터 변경 | 낮음 | 본문 범위 한정 해시 |
| L2 | 본문 내 수치·날짜·고유명사 변경 | **높음** | 본문 diff + 숫자 패턴 비교 |
| L3 | 단락 전체 삭제·추가·재작성 | **매우 높음** | 섹션 단위 diff |

`compare_versions`의 가치를 결정하는 것은 L2·L3 계층이다. L0·L1만 잡힌다면 도구는 소음 생성기다.

## 3. 표본 설계

### 3.1 모집단과 표본 크기

- **모집단**: 2021-04-17 ~ 2026-04-17 사이 중앙부처 보도자료 (약 52,000건 가정)
- **표본**: 단순 무작위 추출 500건. 부처별 균등 아님 — 실제 유통량 반영.
- **통계적 근거**: 기대 비율 0.5% 근처, 95% 신뢰도 ±0.6%p 오차 (`n = z²p(1-p)/e²` 기준 ≈ 530). 500이면 경계 판단 가능.

시간대별 편향을 피하기 위해 **연도별 층화 추출**도 병행 고려:
- 2021~2025: 각 연도 80건씩 = 400
- 2026년(진행 중): 100건
- 합 500

### 3.2 부처 분포

실제 유통량 비례보다 다양성 우선. 편집 관행이 부처마다 다를 수 있음:
- 기재부, 산업부, 과기정통부, 환경부, 교육부, 국토부, 행안부, 보건복지부, 고용노동부, 농림축산식품부 — 각 30~50건
- 나머지 중앙부처에서 잔여 할당

## 4. 관측 스케줄

한 표본을 여러 시점에 재측정해야 변경 곡선이 보인다.

| 시점 | 기준일 T₀ 대비 | 목적 |
|---|---|---|
| T₀ | 베이스라인 | sha256, 본문 해시, 메타해시 저장 |
| T₁ | +1 일 | 당일 정정(가장 빈번한 경우) 포착 |
| T₂ | +7 일 | 주간 정정 |
| T₃ | +30 일 | 월 단위 조용한 수정 |
| T₄ | +90 일 | 오래된 자료의 역 편집 |
| T₅ | +180 일 | 장기 누적 변화 (최종 판단 기준) |

T₀부터 T₅까지 최소 6개월. **T₂(+7일)까지의 중간 결과만으로도 초기 판단은 가능**하지만, "6개월 지나고 조용히 바뀌는 케이스"가 경험상 가장 문제이므로 T₅까지 돌리는 것을 권장.

## 5. 해시 전략

단순 full-HTML sha256은 노이즈(타임스탬프, 조회수, 세션 쿠키 반영 영역 등)에 취약하다. 3단계 해시를 병행:

### 5.1 `hash_raw`
페이지 HTML 그대로의 sha256. 모든 변경을 잡지만 L0 소음도 포함.

### 5.2 `hash_body`
본문 영역만 추출(korea.kr의 경우 `.view_body` 또는 유사 selector) → 공백 정규화 → 한글·한자·영숫자만 남기고 sha256. L1 이상만 검출.

```python
def normalize_body(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one(".view_body") or soup.select_one("article") or soup.body
    text = body.get_text(separator=" ")
    text = re.sub(r"\s+", " ", text)              # 공백 합치기
    text = re.sub(r"[^\w가-힣一-龥]", "", text)   # 의미 문자만
    return hashlib.sha256(text.encode()).hexdigest()
```

### 5.3 `hash_numbers`
본문 텍스트에서 숫자+단위 토큰만 추출해 정렬 후 해시. L2 검출 전용.

```python
def hash_numbers(body_text: str) -> str:
    tokens = re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?\s*(?:만|억|조)?\s*(?:명|원|개|건|%|년)", body_text)
    return hashlib.sha256(" ".join(sorted(tokens)).encode()).hexdigest()
```

세 해시가 모두 일치하면 L0도 없음. `hash_raw`만 바뀌면 L0, `hash_body`가 바뀌면 L1 이상, `hash_numbers`가 바뀌면 L2 확정.

## 6. 베이스라인 수집 스크립트

```python
# snapshot.py — T₀ 또는 임의 T_n 시점 베이스라인 수집
import asyncio, hashlib, re, sqlite3, aiohttp
from bs4 import BeautifulSoup
from datetime import datetime

DB = "silent_overwrite_tracker.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
  briefing_id TEXT,
  url         TEXT,
  fetched_at  TEXT,
  hash_raw    TEXT,
  hash_body   TEXT,
  hash_numbers TEXT,
  body_text   TEXT,          -- L2/L3 사후 diff용 전체 본문 보존
  http_status INTEGER,
  PRIMARY KEY (briefing_id, fetched_at)
);
"""

async def fetch_one(session, briefing_id: str, url: str) -> dict:
    async with session.get(url, timeout=30) as resp:
        html = await resp.text()
        soup = BeautifulSoup(html, "lxml")
        body_el = soup.select_one(".view_body") or soup.select_one("article") or soup.body
        body_text = re.sub(r"\s+", " ", body_el.get_text(separator=" ")) if body_el else ""
        norm_body = re.sub(r"[^\w가-힣一-龥]", "", body_text)
        tokens = re.findall(
            r"\d+(?:,\d{3})*(?:\.\d+)?\s*(?:만|억|조)?\s*(?:명|원|개|건|%|년)",
            body_text)
        return {
            "briefing_id": briefing_id,
            "url": url,
            "fetched_at": datetime.utcnow().isoformat(),
            "hash_raw": hashlib.sha256(html.encode()).hexdigest(),
            "hash_body": hashlib.sha256(norm_body.encode()).hexdigest(),
            "hash_numbers": hashlib.sha256(" ".join(sorted(tokens)).encode()).hexdigest(),
            "body_text": body_text,
            "http_status": resp.status,
        }

async def main(sample_csv: str):
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)
    async with aiohttp.ClientSession(headers={"User-Agent": "govpress-mcp-overwrite-test/0.1"}) as session:
        sem = asyncio.Semaphore(5)           # korea.kr 예의상 동시성 5로 제한
        async def bounded(row):
            async with sem:
                await asyncio.sleep(0.3)     # rate limit 마진
                return await fetch_one(session, row["briefing_id"], row["url"])
        rows = list(csv.DictReader(open(sample_csv, encoding="utf-8")))
        snapshots = await asyncio.gather(*(bounded(r) for r in rows), return_exceptions=True)
        for s in snapshots:
            if isinstance(s, Exception): continue
            conn.execute("""INSERT OR REPLACE INTO snapshots VALUES
              (:briefing_id, :url, :fetched_at, :hash_raw, :hash_body, :hash_numbers, :body_text, :http_status)""", s)
    conn.commit()

if __name__ == "__main__":
    import sys, csv
    asyncio.run(main(sys.argv[1]))
```

실행:
```bash
python snapshot.py sample_500.csv
```

## 7. 비교·분류 스크립트

T₀ 스냅샷과 T_n 스냅샷을 비교해 변경을 L0~L3으로 분류.

```python
# compare.py — 두 시점 스냅샷 비교 리포트 생성
import sqlite3, difflib, re, json

def classify_change(s0: dict, s1: dict) -> str:
    if s0["hash_raw"] == s1["hash_raw"]: return "UNCHANGED"
    if s0["hash_body"] == s1["hash_body"]: return "L0"         # 포맷만
    if s0["hash_numbers"] == s1["hash_numbers"]:
        # body는 바뀌었는데 숫자는 그대로 → L1 또는 L3 재작성(숫자 미동)
        return classify_l1_vs_l3(s0["body_text"], s1["body_text"])
    return "L2"                                                 # 숫자 변경 확정

def classify_l1_vs_l3(text0: str, text1: str) -> str:
    # 문장 단위로 쪼개서 Jaccard 유사도 측정
    sents0 = set(re.split(r"[.!?。]", text0))
    sents1 = set(re.split(r"[.!?。]", text1))
    jaccard = len(sents0 & sents1) / max(1, len(sents0 | sents1))
    return "L1" if jaccard > 0.85 else "L3"

def report(db: str, t0_at: str, t1_at: str):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    results = {"UNCHANGED": 0, "L0": 0, "L1": 0, "L2": 0, "L3": 0}
    cases = []
    for row in conn.execute(
        "SELECT briefing_id FROM snapshots WHERE fetched_at = ? GROUP BY briefing_id", (t0_at,)):
        bid = row["briefing_id"]
        s0 = conn.execute("SELECT * FROM snapshots WHERE briefing_id=? AND fetched_at=?",
                          (bid, t0_at)).fetchone()
        s1 = conn.execute("SELECT * FROM snapshots WHERE briefing_id=? AND fetched_at=?",
                          (bid, t1_at)).fetchone()
        if not s1: continue
        verdict = classify_change(dict(s0), dict(s1))
        results[verdict] += 1
        if verdict in ("L2", "L3"):
            diff = list(difflib.unified_diff(
                s0["body_text"].split(". "), s1["body_text"].split(". "), lineterm=""))
            cases.append({"briefing_id": bid, "verdict": verdict, "diff": diff[:40]})
    print(json.dumps({"counts": results, "total": sum(results.values())}, indent=2))
    json.dump(cases, open("overwrite_cases.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

if __name__ == "__main__":
    import sys
    report("silent_overwrite_tracker.sqlite", sys.argv[1], sys.argv[2])
```

실행:
```bash
python compare.py "2026-04-17T00:00:00" "2026-04-24T00:00:00"
```

## 8. 결정 트리

T₅(+180일)까지의 누적 결과를 기준으로 판단한다. 조기 판단이 필요하면 T₂(+7일) 결과로도 방향을 가늠할 수 있으나 중간 판단은 보류 권장.

```
        L2+L3 합산 비율
              │
   ≤0.5%  ───┤───  0.5~2%  ───┤───  >2%
     │           │                │
   제거       유지             승격
     │        (기본)          (킬러 후보)
     │           │                │
     ▼           ▼                ▼
compare_       experimental     README 다시
versions       뱃지 달고        히어로 영역
명세에서       베타 공개        복귀
완전 제거
```

- **≤0.5%**: 준우의 현재 가정과 일치. 도구 제거. 문서 3종(README·데모·GeekNews)에서 해당 섹션 삭제. 로드맵 Phase F 제거.
- **0.5~2%**: 존재는 하지만 희귀. 도구 유지하되 "experimental" 뱃지, 홍보에서는 조연 취급.
- **>2%**: 준우의 가정이 틀렸음. 도구를 원 명세대로 킬러 3종에 유지.

## 9. 실험 운영 체크리스트

- [ ] 중앙부처 보도자료 500건 무작위 추출 (기간·부처별 층화)
- [ ] `sample_500.csv` 생성 (`briefing_id,url` 2열)
- [ ] T₀ 베이스라인 수집 (`snapshot.py`)
- [ ] korea.kr 크롤 rate 점검 — 429/503 응답 빈도 확인, 필요시 간격 상향
- [ ] T₁(+1d), T₂(+7d) 자동 실행 cron 등록
- [ ] T₂ 중간 리포트 초안 작성
- [ ] T₃~T₅ 스케줄 확인 (180일 뒤 캘린더 리마인더)
- [ ] 최종 결정 트리 적용, 문서 3종 업데이트 또는 유지

## 10. 부수 효과 — 생산 파이프라인으로 승격

이 실험 인프라는 일회성이 아니다. **본 서비스의 적재 파이프라인에 그대로 편입**할 수 있다.

기능 명세 §0.1에서 이미 `sha256`을 frontmatter에 저장하도록 되어 있다. 즉 프로덕션에서도 매일 다시 크롤할 때마다 이전 해시와 비교하면 silent overwrite가 실시간 탐지된다. 이 실험은 본 서비스가 실제로 얼마나 자주 그 분기를 탈지 미리 재는 일이기도 하다.

실험이 "거의 없음"을 확인해 `compare_versions`가 제거되더라도, **탐지 자체는 파이프라인에 남겨둔다**. 어쩌다 한 번 발생하는 L2/L3 변경을 놓치지 않는 것 자체로 데이터 품질 신뢰도를 준다.

## 11. 리스크와 대응

| 리스크 | 영향 | 대응 |
|---|---|---|
| korea.kr이 크롤러 차단 | 실험 중단 | 공식 API 우선 사용, HTML 스크랩은 fallback. User-Agent 명시. |
| URL이 뉴스ID 외에 파라미터 있음 | 중복 수집 | URL 정규화: 쿼리스트링 중 `newsId`만 추출 |
| 본문 selector가 부처 리뉴얼로 변경 | hash_body 실패 | 셀렉터 3단계 fallback (특정 → article → body), 실패 시 에러 로그로 수동 개입 |
| 같은 날 여러 번 수정 | 중간 상태 누락 | 베이스라인을 일 1회가 아닌 시간 단위로 올리는 옵션 |
| 휴일·연휴 수정 집중 | 월별 편차 | 분석 시 "수정일까지의 영업일 경과"를 보조 지표로 |

## 12. 다음 단계

1. 이 문서 리뷰 후 확정
2. `sample_500.csv` 추출 스크립트 작성 (별도 세션)
3. T₀ 스냅샷 돌리고 1주 대기 → T₂ 결과 보고
4. T₂ 결과에 따라 문서 3종의 "검증 대기" 부분을 채우거나 제거
