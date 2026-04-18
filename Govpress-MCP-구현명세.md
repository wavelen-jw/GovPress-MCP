---
title: Govpress MCP 서버 — 기능별 구현 구체화 및 효과 예시
target: 범용 MCP 클라이언트 (Claude Desktop / Claude Code / 기타)
data_scope: 한국 정부 보도자료 5년치 (2021-04 ~ 2026-04, 중앙+광역+기초지자체 전체)
version: 0.2 (2026-04-17 갱신)
date: 2026-04-17
---

# Govpress MCP 서버 — 기능별 구현 구체화 및 효과 예시

> **⚠️ v0.1 → v0.2 갱신 주의사항 (2026-04-17)**
>
> 아래 본문은 v0.1 초안으로, 이후 확정된 결정들과 **7개 지점에서 충돌**한다. 구현 시점에는 `project_govpress_mcp_decisions.md` 메모리와 `데이터-저장-아키텍처.md` §10을 **우선 참조**할 것.
>
> | 구현명세.md (v0.1) 기재 | v0.2 확정 결정 | 참조 |
> |---|---|---|
> | 크롤 범위: 중앙부처 위주 | 전체 (중앙 + 광역 + 기초). 화이트리스트 없음, `entity_type` 필드로 구분 | 저장-아키텍처 §10, 메모리 §3 |
> | 파일 경로: `{year}/{ministry}/{YYYY-MM-DD}-{slug}.md` | `news_item_id` 중심: `md/{yyyy}/{mm}/{news_item_id}.md` | 저장-아키텍처 §10, 메모리 §6.1 |
> | frontmatter 필드: `ministry` | `department` + `entity_type` (central/metro/local) | AGENTS.md §1.7 |
> | 원본 포맷: PDF | HWPX | 메모리 §3 |
> | 배포: fly.io | 서버W(WSL+Docker) + Cloudflare Tunnel (`mcp.govpress.cloud`) | 메모리 §2 |
> | 토큰나이저: mecab-ko 기본 채택 | unicode61+trigram 기본 + Phase B 전 실험으로 확정 | 메모리 §6.3 |
> | 로드맵 Phase A-G (13주) | Phase 1 착수 (10건 E2E) → Phase 2(색인) → Phase 3(MCP 서버) … AGENTS.md 기준 | codex-handoff/AGENTS.md |
>
> 각 도구의 **구현 의도와 효과 예시는 유효**하다. 위 7가지 물리적 결정만 최신 값으로 치환하면서 읽어라.

본 문서는 「Govpress MCP 서버 기능 명세」에 기술된 8개 도구 각각에 대해 (1) 내부적으로 어떻게 구현할 것인지, (2) 실제 한국 정부 보도자료 5년치를 적재했을 때 어떤 질의에 어떤 답이 나오는지, (3) 해당 도구가 없을 때와 비교해 무엇이 달라지는지를 정리한다. 모든 예시는 가상의 보도자료 ID와 수치를 사용하되, 정부 보도자료의 실제 포맷·용어·주제 분포를 최대한 반영했다.

## 0. 전제: 데이터 인프라 구현 세부

기능 명세 §0에서 요구한 자산(Git 기반 MD 리포지토리, 벡터 DB, 메타데이터 DB)을 실제로 구축하는 파이프라인을 먼저 정리한다. 이 인프라가 없으면 8개 도구 중 어느 하나도 동작하지 않는다.

### 0.1 적재 파이프라인(ETL)

보도자료가 정책브리핑(korea.kr) API 또는 사전 수집한 PDF 아카이브에서 들어오는 순간을 기준으로, 다음 단계가 순차 실행된다.

```
[PDF 원본]
   ↓ (Govpress v0.3.x 변환 엔진)
[Markdown + frontmatter]
   ↓ (정규화 / 중복 제거)
[briefings 테이블 INSERT]
   ↓ (섹션 청킹)
[청크 단위 임베딩 → Qdrant upsert]
   ↓ (숫자 패턴 추출 + LLM 라벨링)
[statistics 테이블 INSERT]
   ↓
[Git commit → push]
```

핵심 포인트:

- **파일 경로 규약 고정**: `{year}/{ministry}/{YYYY-MM-DD}-{slug}.md`. 슬러그는 원문 제목을 하이픈 케이스로 변환하되 50자 cap. 동일 날짜·동일 제목 충돌 시 `-2` suffix.
- **정정 탐지**: 기존 파일이 있는데 새 버전이 도착하면, 파일을 덮어쓰고 commit 메시지를 `correction: {briefing_id} r{n}` 포맷으로 남긴다. 이 메시지 규약이 도구 5(compare_versions)의 파싱 키다.
- **frontmatter 필수 필드**: `id`, `title`, `ministry`, `date`, `url`, `sha256`, `revision`, `extracted_by`. `sha256`은 원본 PDF의 해시로, 동일 PDF 재수신 판별에 쓴다.

### 0.2 청킹 전략

보도자료는 통상 500~3000어절, 섹션 구조가 비교적 규칙적이다(개요 / 추진배경 / 주요내용 / 기대효과 / 향후계획 / 별첨). 청킹은 이 섹션 헤더를 1차 분할 경계로 사용한다.

```python
def chunk_briefing(md: str, briefing_id: str) -> list[Chunk]:
    sections = split_by_headers(md, levels=[2, 3])   # ## / ### 기준
    chunks = []
    for idx, (section_title, body) in enumerate(sections):
        if len(body) < 200:
            continue                                  # 너무 짧은 헤더는 병합 대상
        for sub_idx, window in sliding_window(body, size=400, overlap=80):
            chunks.append(Chunk(
                chunk_id=f"{briefing_id}#{idx}.{sub_idx}",
                briefing_id=briefing_id,
                section=section_title,
                text=window,
            ))
    return merge_tiny(chunks)
```

청크당 400토큰 근처 + 20% overlap이 보도자료 구조와 실제로 잘 맞았다. 표(markdown table)는 절대 중간에서 자르지 않고 통째로 한 청크로 보존한다(`|`행이 연속되는 구간을 원자 단위로 취급).

### 0.3 statistics 테이블 사전 적재

도구 4(cross_check_ministries)와 도구 8(validate_statistics)이 둘 다 이 테이블을 조회한다. 보도자료가 들어올 때마다 아래 두 단계를 돌려 미리 채운다.

**Step 1 — 정규식 추출**: `\d+(?:,\d{3})*(?:\.\d+)?\s*(?:만|억|조)?\s*(?:명|원|개|건|%|톤|kW|GW)` 같은 패턴으로 후보를 수집. 이 단계에서 false positive가 많아도 괜찮다.

**Step 2 — LLM 라벨링**: 각 후보 숫자 주변 ±80자를 컨텍스트로 묶어 작은 모델(Claude Haiku 등)에게 던진다. 프롬프트는 "이 숫자가 표현하는 정책지표의 이름을 명사구로, 목표 연도가 있으면 함께 뽑아줘" 한 줄짜리. 출력은 JSON으로 강제.

```json
{
  "metric": "AI 인재 양성 규모",
  "value": 500000,
  "unit": "명",
  "year_target": 2027,
  "context": "...2027년까지 AI 인재 50만 명을 양성하여..."
}
```

라벨링이 실패하거나 metric이 공백이면 버린다. 하루 100~200건 수준의 보도자료 처리량에서 Haiku 비용은 무시할 수 있다.

---

## 1. search_briefing — 기본 검색

### 1.1 구현 상세

세 모드(`keyword` / `semantic` / `hybrid`)를 하나의 엔드포인트로 노출한다. 내부적으로는 필터링 → 스코어링 → 랭킹의 3단 파이프라인이다.

```python
async def search_briefing(
    query: str,
    date_from: str | None = None,
    date_to: str | None = None,
    ministry: str | None = None,
    limit: int = 10,
    mode: Literal["keyword", "semantic", "hybrid"] = "keyword",
) -> SearchResult:
    # 1. 사전 필터 — SQL로 후보 briefing_id 집합 좁히기
    candidate_ids = await filter_briefings(date_from, date_to, ministry)

    # 2. 모드별 스코어링
    if mode == "keyword":
        hits = fts5_search(query, candidate_ids, limit * 3)
    elif mode == "semantic":
        q_vec = await embed(query)
        hits = qdrant_search(q_vec, candidate_ids, limit * 3)
    else:  # hybrid
        kw_hits = fts5_search(query, candidate_ids, limit * 3)
        sem_hits = qdrant_search(await embed(query), candidate_ids, limit * 3)
        hits = reciprocal_rank_fusion(kw_hits, sem_hits, k=60)

    # 3. 청크 단위 결과 → briefing 단위로 집계 (같은 brief이면 최고 스코어만)
    return aggregate_by_briefing(hits, limit=limit)
```

구현 시 주의점:

- **부처명 부분 일치**: "기재부"와 "기획재정부"가 모두 매칭되어야 한다. 적재 시 `ministry_alias` 컬럼에 축약형까지 저장(`["기획재정부", "기재부"]`)하고 쿼리 시 `ARRAY_CONTAINS`로 처리.
- **한국어 형태소 분리**: FTS5의 기본 토크나이저는 공백 분리만 해서 "탄소중립"과 "탄소 중립"을 별개로 본다. `unicode61` 토크나이저 + 자체 토큰화 전처리(mecab-ko 또는 soynlp)로 복합명사를 분리해 저장.
- **limit * 3 오버페치**: 청크 단위 hit를 briefing 단위로 dedupe할 때 손실분을 감안.
- **score 정규화**: 세 모드의 score 범위가 달라서 응답 형식은 0~1 min-max로 통일.

### 1.2 효과 예시

**시나리오** — 사용자: "2025년 산업부가 낸 반도체 관련 보도자료 찾아줘"

**이 도구 없이 (Claude가 맨손으로)**:
- Claude는 `korea.kr`에서 직접 검색하도록 웹 fetch를 시도하거나, 일반 웹 검색에 의존
- 결과가 최신순이 아닐 수 있고, 정확한 본문 대신 요약 스니펫만 반환됨
- 부처 필터가 완전하지 않아 지자체·국회 자료가 섞임

**이 도구 사용 (`mode="hybrid"`)**:

호출:
```json
{
  "query": "반도체",
  "date_from": "2025-01-01",
  "date_to": "2025-12-31",
  "ministry": "산업통상자원부",
  "mode": "hybrid",
  "limit": 10
}
```

가상 응답:
```json
{
  "total": 34,
  "returned": 10,
  "results": [
    {
      "id": "156711203",
      "title": "K-반도체 전략 2025 수정보완 방안",
      "ministry": "산업통상자원부",
      "date": "2025-06-18",
      "snippet": "...용인 클러스터 착공 시점을 2025년 말로 앞당기고, 소부장 국산화 목표를 45%에서 50%로 상향...",
      "score": 0.91
    },
    {
      "id": "156698441",
      "title": "반도체 특별법 후속조치 점검회의 결과",
      "ministry": "산업통상자원부",
      "date": "2025-03-22",
      "snippet": "...세액공제 15%가 시행된 이후 투자집행 속도가 42% 증가...",
      "score": 0.88
    }
  ]
}
```

**달라지는 것**: hybrid 모드 덕분에 "반도체"라는 직접 키워드가 없어도 "소부장", "파운드리", "용인 클러스터" 같은 연관어가 포함된 자료를 함께 건진다(semantic). 동시에 FTS5 경로에서는 제목에 "반도체"가 들어간 고신뢰 결과가 상위에 보장된다(keyword). hybrid는 이 두 경로의 Reciprocal Rank Fusion이라 리콜과 프리시전 양쪽이 모두 개선된다.

---

## 2. get_briefing — 본문 조회

### 2.1 구현 상세

가장 단순한 도구지만 토큰 경제성이 핵심이다. 5년치 보도자료 중 긴 것은 본문만 2만자를 넘는 경우가 있어(예: 예산안 발표) `max_chars` 처리가 중요하다.

```python
async def get_briefing(
    id: str,
    include_metadata: bool = True,
    max_chars: int | None = None,
) -> BriefingContent:
    # 1. Redis LRU 캐시 조회
    cached = await redis.get(f"briefing:{id}")
    if cached and not include_metadata_changed:
        return cached

    # 2. 파일 시스템에서 직접 읽기
    path = resolve_path(id)                  # briefings 테이블에 path 컬럼 보관
    raw = await aiofiles.read(path)
    frontmatter, body = split_frontmatter(raw)

    # 3. 잘라내기 — 섹션 경계 우선, 문자 경계 차선
    if max_chars and len(body) > max_chars:
        body = smart_truncate(body, max_chars)

    # 4. LRU 적재
    await redis.setex(f"briefing:{id}", 3600, result)
    return result
```

`smart_truncate`는 단순히 `[:max_chars]`가 아니라 마지막 `##` 또는 `###` 헤더를 찾아 그 지점까지 반환한 뒤 `\n\n[...이하 생략 (총 N자 중 M자)...]\n` 마커를 붙인다. Claude가 본문을 요약할 때 잘린 위치가 명확해야 "이 부분은 모른다"고 정직하게 답할 수 있다.

캐시 정책:
- TTL 1시간, 최대 500건. 5년치 데이터에서 자주 조회되는 핫셋은 전체의 5% 미만이므로 500건이면 충분.
- 정정 발생 시 `invalidate_cache(briefing_id)` 훅을 Git post-commit에서 호출.

### 2.2 효과 예시

**시나리오** — Claude가 검색 결과 중 `156711203`의 전체 본문이 필요한 상황.

호출:
```json
{ "id": "156711203", "max_chars": 8000 }
```

가상 응답:
```json
{
  "id": "156711203",
  "title": "K-반도체 전략 2025 수정보완 방안",
  "metadata": {
    "ministry": "산업통상자원부",
    "date": "2025-06-18",
    "url": "https://www.korea.kr/briefing/pressReleaseView.do?newsId=156711203",
    "revision": 1
  },
  "markdown": "# K-반도체 전략 2025 수정보완 방안\n\n## 1. 추진배경\n...\n## 2. 주요 내용\n### 2.1 용인 반도체 클러스터\n용인 클러스터 착공 시점을 당초 2026년 상반기에서 **2025년 말**로 앞당긴다...\n\n[...이하 생략 (총 11,420자 중 8,000자)...]",
  "char_count": 11420,
  "truncated": true
}
```

**달라지는 것**: 단순해 보여도 이 도구 없이는 Claude가 URL을 fetch해서 HTML을 파싱해야 한다. 그 과정에서 (a) 광고·네비게이션 영역이 본문에 섞이고, (b) korea.kr의 첨부 PDF 링크는 따로 따라가야 하며, (c) 표는 HTML table이라 마크다운으로 정돈되지 않는다. `get_briefing`은 PDF→MD 변환기를 거친 정제된 본문을 반환하기 때문에 Claude의 후속 인용·요약 정확도가 체감상 크게 올라간다.

---

## 3. trace_policy — 정책 변천사 추적 (킬러)

### 3.1 구현 상세

이 도구의 본질은 "검색을 잘 하는 것"이 아니라 **시계열 버킷팅 + 대표 문서 선정**이다. 결과를 던져줬을 때 Claude가 "아, 이 주제는 2023년에 전환점이 있었구나"를 자연스럽게 읽어낼 수 있어야 한다.

```python
async def trace_policy(
    keyword: str,
    date_from: str = None,           # 기본: today - 5y
    date_to: str = None,             # 기본: today
    granularity: Literal["year", "quarter", "month"] = "year",
) -> PolicyTimeline:
    # 1. 광범위 semantic search — 키워드 1개로는 놓치는 게 많아 확장
    expanded = await expand_keyword(keyword)     # "디지털플랫폼정부" → [..., "DPG", "디지털정부혁신"]
    hits = await semantic_search(expanded, date_from, date_to, top_k=500)

    # 2. 버킷팅
    buckets = defaultdict(list)
    for hit in hits:
        bucket_key = bucket_of(hit.date, granularity)
        buckets[bucket_key].append(hit)

    # 3. 버킷별 대표 문서 선정 — 클러스터 중심
    timeline = []
    for period, items in sorted(buckets.items()):
        centroid = mean([h.embedding for h in items])
        key_briefings = nsmallest(3, items, key=lambda h: cosine_dist(h.embedding, centroid))
        timeline.append(PeriodSlice(
            period=period,
            count=len(items),
            ministries=list({h.ministry for h in items}),
            key_briefings=[as_summary(h) for h in key_briefings],
            summary_hint=None,               # Claude에게 맡김
        ))

    # 4. 부처별 건수 evolution (heatmap 재료)
    ministry_evolution = build_evolution(hits, buckets.keys())
    return PolicyTimeline(keyword, len(hits), timeline, ministry_evolution)
```

`expand_keyword`는 단순 동의어 사전이 아니라 **"같은 정책을 정부가 부르는 여러 이름"** 을 담는다. 예를 들어 "디지털플랫폼정부"는 초기에 "디지털정부혁신"으로 불렸다. 이 변환을 수기로 유지하기 힘들면, 데이터 적재 파이프라인에서 LLM으로 사전 생성해 `policy_aliases` 테이블에 저장한다.

`summary_hint`를 **일부러 비워서** 반환하는 것이 이 도구의 설계 의도다. Claude가 빈 필드를 보면 자기가 채우려고 추론을 시작한다 — 사전 계산된 요약을 박아두면 Claude가 그걸 그대로 인용하고 끝내버린다.

### 3.2 효과 예시

**시나리오** — 사용자: "디지털플랫폼정부 정책이 어떻게 발전해왔는지 5년간 추이로 분석해줘"

호출:
```json
{ "keyword": "디지털플랫폼정부", "granularity": "year" }
```

가상 응답:
```json
{
  "keyword": "디지털플랫폼정부",
  "total_briefings": 87,
  "timeline": [
    {
      "period": "2022",
      "count": 12,
      "ministries": ["과학기술정보통신부", "행정안전부"],
      "key_briefings": [
        { "id": "156503210", "title": "디지털플랫폼정부 비전 선포식 개최", "date": "2022-09-02" },
        { "id": "156512044", "title": "디지털플랫폼정부위원회 출범", "date": "2022-09-28" }
      ]
    },
    {
      "period": "2023",
      "count": 28,
      "ministries": ["과학기술정보통신부", "행정안전부", "기획재정부"],
      "key_briefings": [
        { "id": "156588901", "title": "디지털플랫폼정부 실현계획 발표", "date": "2023-04-14" },
        { "id": "156601180", "title": "2024년 DPG 예산 9,262억원 편성", "date": "2023-08-29" }
      ]
    },
    {
      "period": "2024",
      "count": 22,
      "ministries": ["행정안전부", "과학기술정보통신부", "개인정보보호위원회"],
      "key_briefings": [
        { "id": "156645330", "title": "마이데이터 2.0 로드맵", "date": "2024-03-07" }
      ]
    },
    {
      "period": "2025",
      "count": 17,
      "ministries": ["행정안전부", "과학기술정보통신부"],
      "key_briefings": [
        { "id": "156698712", "title": "AI 행정서비스 전환 가속화 방안", "date": "2025-05-22" }
      ]
    },
    {
      "period": "2026",
      "count": 8,
      "ministries": ["과학기술정보통신부"],
      "key_briefings": [
        { "id": "156720115", "title": "디지털플랫폼정부 2026년 추진계획", "date": "2026-01-15" }
      ]
    }
  ],
  "ministry_evolution": {
    "과학기술정보통신부": [8, 15, 9, 11, 6],
    "행정안전부": [4, 10, 11, 5, 1],
    "기획재정부": [0, 3, 2, 1, 1]
  }
}
```

**Claude가 이 데이터로 생성하는 분석(예상)**:
> 2022년은 비전 발표 중심으로 과기정통부·행안부 주도였고, 2023년에 기재부가 합류하며 예산 편성 단계로 전환되었습니다. 2024년부터 행안부 비중이 역전되는데, 마이데이터 2.0·AI 행정 같은 집행 단계로 넘어가면서 주관 부처가 바뀐 것으로 보입니다. 2025년 이후 건수가 감소한 것은 정책 성숙기로의 진입 혹은 관심 이동을 시사합니다.

**달라지는 것**: 이 도구 없이 Claude가 같은 분석을 하려면 `search_briefing`을 10번 넘게 호출해 직접 시계열을 재구성해야 한다. 가능은 하지만 (a) 컨텍스트 소모가 10배, (b) 대표 보도자료 선정이 단순 "최신순"으로 편향되어 정책 전환점을 놓치기 쉽다. `trace_policy`는 **centroid 기반 대표 선정** 덕분에 해당 시기의 "중앙값 같은" 보도자료를 집어주고, 이게 변천사 스토리라인을 만든다.

---

## 4. cross_check_ministries — 부처간 정책 비교 (킬러)

### 4.1 구현 상세

이 도구는 기자 관점의 "엇박자 찾기"가 핵심 가치다. 구현은 3레이어.

```python
async def cross_check_ministries(
    topic: str,
    date_from: str = None,                       # 기본: today - 1y
    date_to: str = None,
    min_ministries: int = 2,
) -> CrossCheckResult:
    # Layer 1 — 주제 관련 보도자료 수집
    hits = await semantic_search(topic, date_from, date_to, top_k=200)
    by_ministry = groupby(hits, key=lambda h: h.ministry)
    if len(by_ministry) < min_ministries:
        return CrossCheckResult(topic, [], [])

    # Layer 2 — 각 보도자료의 핵심 수치 추출
    ministries_involved = []
    all_claims = []
    for ministry, items in by_ministry.items():
        briefings_out = []
        for h in items[:5]:                      # 부처별 상위 5건
            stats = await fetch_stats(h.briefing_id, topic_filter=topic)
            key_numbers = [f"{s.value}{s.unit}" for s in stats[:3]]
            briefings_out.append({
                "id": h.briefing_id, "date": h.date, "title": h.title,
                "key_numbers": key_numbers,
            })
            all_claims.extend((ministry, h, s) for s in stats)
        ministries_involved.append({"ministry": ministry, "briefings": briefings_out})

    # Layer 3 — 충돌 후보 탐지
    conflicts = detect_conflicts(all_claims)
    return CrossCheckResult(topic, ministries_involved, conflicts)
```

`detect_conflicts`는 의미 유사한 metric끼리 값이 다를 때 후보로 올린다. "AI 인재 양성 규모" vs "AI 핵심인재 배출"처럼 metric 명이 살짝 달라도 임베딩 유사도 >0.85면 같은 지표로 묶는다.

```python
def detect_conflicts(claims: list[tuple[str, Hit, Stat]]) -> list[Conflict]:
    # metric 임베딩으로 클러스터링
    metric_vecs = [embed(s.metric) for (_, _, s) in claims]
    clusters = agglomerative_cluster(metric_vecs, threshold=0.15)

    conflicts = []
    for cluster in clusters:
        members = [claims[i] for i in cluster]
        if len({s.value for (_, _, s) in members}) < 2:
            continue                             # 같은 값이면 충돌 아님
        # 단위 불일치는 별도 충돌 타입
        units = {s.unit for (_, _, s) in members}
        conflict_type = "unit_mismatch" if len(units) > 1 else "number_mismatch"
        conflicts.append(Conflict(
            type=conflict_type,
            description=describe(cluster),
            evidence=[{"ministry": m, "claim": s.context, "source_id": h.briefing_id}
                      for (m, h, s) in members],
        ))
    return conflicts
```

**설계 원칙**: "진짜 충돌인지"를 서버가 판단하지 않는다. 단위·시점·범위의 차이는 문맥을 봐야 알 수 있고, 이건 Claude가 잘한다. 서버는 후보를 넉넉히 내놓는 역할만.

### 4.2 효과 예시

**시나리오** — 기자: "AI 인재양성 관련해서 부처별로 엇박자 있는 거 없나 체크"

호출:
```json
{ "topic": "AI 인재양성", "date_from": "2025-01-01" }
```

가상 응답 (요약):
```json
{
  "topic": "AI 인재양성",
  "ministries_involved": [
    {
      "ministry": "과학기술정보통신부",
      "briefings": [
        { "id": "156703118", "date": "2025-08-12", "title": "AI 생태계 활성화 방안",
          "key_numbers": ["50만 명", "2027년", "3조 2천억원"] }
      ]
    },
    {
      "ministry": "교육부",
      "briefings": [
        { "id": "156705942", "date": "2025-09-03", "title": "디지털 인재 양성 5개년 계획",
          "key_numbers": ["20만 명", "2026년", "1조 4천억원"] }
      ]
    },
    {
      "ministry": "고용노동부",
      "briefings": [
        { "id": "156708701", "date": "2025-10-11", "title": "신산업 직업훈련 개편안",
          "key_numbers": ["8만 명", "매년", "4천억원"] }
      ]
    }
  ],
  "potential_conflicts": [
    {
      "type": "number_mismatch",
      "description": "동일 또는 유사한 AI 인재 양성 규모 지표에 대해 부처별 수치가 다릅니다",
      "evidence": [
        { "ministry": "과학기술정보통신부", "claim": "AI 인재 50만 명을 2027년까지", "source_id": "156703118" },
        { "ministry": "교육부", "claim": "디지털·AI 인재 20만 명을 2026년까지", "source_id": "156705942" }
      ]
    }
  ]
}
```

**Claude의 후속 해석(예상)**:
> 두 수치의 대상 정의가 다를 가능성이 높습니다. 과기정통부의 50만 명은 "AI를 활용·개발할 수 있는 광의의 인재"로 보이고, 교육부의 20만 명은 "정규교육 과정에서 양성되는 디지털 전공자"에 한정되는 것으로 읽힙니다. 기사로 쓰려면 양 부처에 "중복 집계가 있느냐"를 직접 묻는 것이 안전합니다.

**달라지는 것**: 이 도구 없이 기자가 같은 결론에 도달하려면 부처별 보도자료를 각각 읽고, 숫자를 수기로 대조하고, 시점 차이를 감안해야 한다. 보통 이 과정에서 "한쪽 보도자료만 보고 쓴 기사"가 나온다. `cross_check_ministries`는 **충돌 후보 자동 적시**로 이 대조 비용을 거의 0에 가깝게 만든다.

---

## 5. compare_versions — 정정 전후 비교

### 5.1 구현 상세

Git 리포 구조를 그대로 활용한다. 핵심은 commit message의 규약(`correction: {id} r{n}`)을 파싱해 리비전 번호를 붙이는 것.

```python
async def compare_versions(
    briefing_id: str,
    revision: int | None = None,
) -> VersionHistory:
    path = resolve_path(briefing_id)
    log = await git_log(path, format="%H|%aI|%s")    # commit SHA, 작성일, 메시지

    revisions = []
    for rev_num, (sha, date, msg) in enumerate(log, start=1):
        change_type = "initial" if rev_num == 1 else "correction"
        summary = None
        diff = None
        if change_type == "correction":
            diff = await git_show(sha, path)
            summary = await llm_summarize_diff(diff)  # 적재 시 사전 생성한 걸 캐싱
        revisions.append(Revision(
            revision=rev_num, date=date, commit_sha=sha,
            change_type=change_type, diff=diff, summary=summary,
        ))

    if revision is not None:
        revisions = [r for r in revisions if r.revision == revision]
    return VersionHistory(briefing_id, revisions)
```

주의점:

- **diff 포맷**: unified diff 그대로 주되, 150줄 초과 시 `... (N lines snipped) ...` 자르기. Claude가 diff 전체를 읽지 않고도 변화 지점을 찾을 수 있도록 `@@` hunk별로 요약도 함께 제공.
- **요약 생성 시점**: 실시간이 아니라 정정 감지 후 commit 직후 1회. 결과는 `revision_summaries` 테이블에 `(briefing_id, revision, summary)`로 저장.
- **정정이 아닌 커밋 혼입 방지**: 메타데이터 보정(예: ministry 이름 오타 수정)은 commit 메시지를 `meta: ...`로 시작해서 리비전 카운트에서 제외한다.

### 5.2 효과 예시

**시나리오** — 사용자: "이 보도자료 원래 2026년까지라고 했다가 2027년으로 바뀐 거 아니야? 언제 정정됐지?"

호출:
```json
{ "briefing_id": "156720115" }
```

가상 응답:
```json
{
  "id": "156720115",
  "title": "디지털플랫폼정부 2026년 추진계획",
  "revisions": [
    {
      "revision": 1,
      "date": "2026-01-15T09:00:00+09:00",
      "commit_sha": "a3f5c11...",
      "change_type": "initial"
    },
    {
      "revision": 2,
      "date": "2026-01-15T14:30:00+09:00",
      "commit_sha": "7d8e42a...",
      "change_type": "correction",
      "diff": "@@ -42,1 +42,1 @@\n-AI 공공서비스 50개를 2026년까지 완비\n+AI 공공서비스 50개를 2027년까지 완비",
      "summary": "AI 공공서비스 완비 목표 연도를 2026년에서 2027년으로 1년 연기"
    }
  ]
}
```

**달라지는 것**: 보도자료는 당일 오후에 조용히 정정되는 경우가 많고, 원문 URL은 덮어쓰기라 차이를 확인할 방법이 공식 채널에 없다. 이 도구는 **정책의 git blame**을 제공해 "언제, 무엇이, 어느 방향으로 바뀌었는가"를 기자·연구자·정책 분석가가 5초 만에 확인하게 한다. 홍보 시 GIF로 시연하면 임팩트가 가장 큰 기능 중 하나다.

---

## 6. list_ministries_by_topic — 주제별 부처 분포

### 6.1 구현 상세

가장 가벼운 도구. SQL 한 방으로 끝나지만, 보도자료가 여러 부처 공동 발표인 경우를 잘 처리해야 한다.

```python
async def list_ministries_by_topic(
    query: str,
    date_from: str = None,
    date_to: str = None,
) -> MinistryDistribution:
    # 1. semantic search로 후보 briefing_id 수집 (top 1000 정도로 넉넉히)
    candidate_ids = await semantic_search_ids(query, date_from, date_to, top_k=1000)

    # 2. SQL로 부처별 집계
    rows = await db.fetch("""
        SELECT ministry, COUNT(*) AS cnt,
               MIN(date) AS first_date, MAX(date) AS last_date
        FROM briefings
        WHERE id = ANY($1)
        GROUP BY ministry
        ORDER BY cnt DESC
    """, candidate_ids)
    return MinistryDistribution(query, len(candidate_ids), [dict(r) for r in rows])
```

**공동발표 처리**: `briefings.ministry`를 배열 컬럼으로 두거나, `briefing_ministries` 매핑 테이블을 별도로 둔다. 후자가 정규형이라 권장. 공동발표 보도자료는 행이 여러 번 카운트되어야 "실제 참여한 부처"가 다 드러난다.

### 6.2 효과 예시

**시나리오** — 사용자: "탄소중립 관련해서 어느 부처들이 주로 목소리를 냈어?"

호출:
```json
{ "query": "탄소중립", "date_from": "2021-01-01" }
```

가상 응답:
```json
{
  "query": "탄소중립",
  "total_briefings": 234,
  "ministries": [
    { "name": "환경부", "count": 87, "first_date": "2021-03-12", "last_date": "2026-04-08" },
    { "name": "산업통상자원부", "count": 56, "first_date": "2021-05-20", "last_date": "2026-03-15" },
    { "name": "국토교통부", "count": 34, "first_date": "2022-01-08", "last_date": "2026-02-28" },
    { "name": "기획재정부", "count": 22, "first_date": "2021-07-01", "last_date": "2025-11-30" },
    { "name": "농림축산식품부", "count": 18, "first_date": "2022-03-03", "last_date": "2026-01-22" }
  ]
}
```

**달라지는 것**: Claude가 이 결과만 보고도 "환경부가 프레임을, 산업부가 구체 조치를, 국토부가 건물·모빌리티 쪽을 맡는 분담 구조"를 즉시 읽어낸다. 이 도구는 그 자체로 답변이 되기보다 **다른 도구(특히 trace_policy, cross_check_ministries)의 사전 탐색용**으로 가장 자주 호출될 것이다. "어느 부처를 깊이 볼지" 정하는 진입점 역할.

---

## 7. get_briefing_context — 정책 맥락 조회

### 7.1 구현 상세

"이 보도자료 하나가 어떤 흐름의 중간에 있는지"를 보여준다. 핵심은 단순 시간 윈도우가 아니라 **의미 유사도 + 인접 시점**의 교집합이다.

```python
async def get_briefing_context(
    id: str,
    window: int = 6,                          # ±개월
) -> BriefingContextOut:
    target = await get_briefing(id)
    target_vec = await get_briefing_embedding(id)

    delta = relativedelta(months=window)
    preceding_cands = await find_briefings(
        date_from=target.date - delta, date_to=target.date - timedelta(days=1),
    )
    following_cands = await find_briefings(
        date_from=target.date + timedelta(days=1), date_to=target.date + delta,
    )

    # 각 후보의 임베딩과 cosine similarity 상위 N
    preceding = top_k_by_similarity(preceding_cands, target_vec, k=5, min_sim=0.75)
    following = top_k_by_similarity(following_cands, target_vec, k=5, min_sim=0.75)

    related_topics = await fetch_topic_tags(id)
    return BriefingContextOut(
        id=id, title=target.title,
        context={
            "preceding": [{"id": p.id, "date": p.date, "title": p.title, "relation": None}
                          for p in preceding],
            "following": [{"id": f.id, "date": f.date, "title": f.title, "relation": None}
                          for f in following],
            "related_topics": related_topics,
        },
    )
```

`relation`을 비워두는 것은 의도적이다(trace_policy의 summary_hint와 같은 철학). Claude가 문맥을 읽고 "예산 편성 → 시범사업 → 확산"같은 단계 라벨을 붙이게 한다.

**min_sim 임계값**이 경험적으로 중요하다. 0.75 미만을 포함하면 "같은 달의 무관한 보도자료"가 섞인다. 이 값은 프로덕션에서 로그 보고 튜닝 대상.

### 7.2 효과 예시

**시나리오** — 사용자: "이 보도자료 앞뒤로 어떤 흐름이 있었는지 맥락 좀"

호출:
```json
{ "id": "156720115", "window": 6 }
```

가상 응답:
```json
{
  "id": "156720115",
  "title": "디지털플랫폼정부 2026년 추진계획",
  "context": {
    "preceding": [
      { "id": "156712803", "date": "2025-08-28", "title": "2026년 정부예산안 — DPG 7,800억원 편성", "relation": null },
      { "id": "156717550", "date": "2025-11-14", "title": "DPG 성과평가 및 개선과제 도출", "relation": null },
      { "id": "156719002", "date": "2025-12-19", "title": "AI 공공서비스 실증사업 결과보고", "relation": null }
    ],
    "following": [
      { "id": "156721440", "date": "2026-02-20", "title": "DPG 1차 점검회의 결과", "relation": null },
      { "id": "156723115", "date": "2026-03-28", "title": "마이데이터 3.0 서비스 개시", "relation": null }
    ],
    "related_topics": ["디지털트윈", "공공데이터 개방", "AI 행정서비스", "마이데이터"]
  }
}
```

**Claude의 후속 해석(예상)**: preceding은 "예산 확정 → 성과평가 → 실증사업"의 3단계 준비 과정, following은 "추진계획 발표 직후 점검 → 구체 서비스 출시"의 집행 과정임을 읽어낸다. 사용자는 질문 1개로 이 맥락 지도를 얻는다.

**달라지는 것**: 이 도구는 단독으로는 작고 지루해 보이지만, **trace_policy나 get_briefing의 답변 품질을 받쳐주는 조연** 역할을 한다. 특히 정책연구자가 "왜 이 시점에 이게 나왔나"를 물을 때 필수.

---

## 8. validate_statistics — 초안 숫자 검증 (B2G 킬러)

### 8.1 구현 상세

가장 복잡하고 가장 가치가 크다. 정부 부처 내부에서 "보도자료 초안 다 써놨는데 과거 발표랑 안 맞으면 어쩌지" 하는 두려움을 직접 해소한다. 3단계 파이프라인:

```python
async def validate_statistics(
    draft_text: str,
    context_window_months: int = 24,
    ministry: str | None = None,
) -> ValidationReport:
    # Step 1 — claim 추출
    claims = await extract_claims(draft_text)
    if not claims:
        return ValidationReport(extracted_claims=[], validations=[])

    # Step 2 — 각 claim에 대해 과거 발표 후보 조회
    validations = []
    date_from = today() - relativedelta(months=context_window_months)
    for c in claims:
        candidates = await find_past_statements(
            metric=c.metric, metric_vec=c.metric_vec,
            ministry=ministry, date_from=date_from,
        )
        if not candidates:
            validations.append(Validation(claim=c, status="new", past_statements=[]))
            continue

        # Step 3 — 충돌 판정은 후보를 넉넉히 주는 데 그침
        status, suggestion = triage(c, candidates)
        validations.append(Validation(
            claim=c, status=status, past_statements=candidates[:5],
            suggestion=suggestion,
        ))

    return ValidationReport(claims, validations)
```

**Step 1 — extract_claims** 세부:

```python
async def extract_claims(draft: str) -> list[Claim]:
    # 1차: 정규식 — 넓게
    raw = list(re.finditer(
        r'(?P<num>\d+(?:,\d{3})*(?:\.\d+)?)\s*(?P<scale>만|억|조)?\s*'
        r'(?P<unit>명|원|개|건|%|톤|kW|GW|년|개월)',
        draft))
    if not raw:
        return []

    # 2차: 각 매치 주변 ±80자 snippet으로 LLM에 metric 라벨 요청 (배치)
    snippets = [(m, draft[max(0, m.start()-80):m.end()+80]) for m in raw]
    metrics = await haiku_label_metrics([s for _, s in snippets])

    claims = []
    for (m, _), meta in zip(snippets, metrics):
        if not meta.get("metric"):
            continue
        claims.append(Claim(
            metric=meta["metric"],
            metric_vec=await embed(meta["metric"]),
            value=normalize(m.group("num"), m.group("scale")),
            unit=m.group("unit"),
            year_target=meta.get("year_target"),
            snippet=snippets[raw.index(m)][1],
        ))
    return claims
```

**Step 2 — find_past_statements** 세부: SQLite의 `statistics` 테이블에서 metric 임베딩 유사도 > 0.82 + 단위 일치 + 날짜 범위 조건. 이 세 조건의 AND로 과거 후보를 좁힌다. 단위 일치 조건이 없으면 "50억 원"과 "50억 톤"을 같은 후보로 묶는 사고가 발생.

**Step 3 — triage** 세부:

```python
def triage(claim: Claim, past: list[PastStmt]) -> tuple[Status, str | None]:
    past_values = [p.value for p in past]
    if all(p == claim.value for p in past_values):
        return "consistent", None
    # 시점 차이 감안
    same_year_past = [p for p in past if p.year_target == claim.year_target]
    if same_year_past and any(p.value != claim.value for p in same_year_past):
        deltas = [claim.value - p.value for p in same_year_past]
        direction = "증가" if all(d > 0 for d in deltas) else "감소" if all(d < 0 for d in deltas) else "혼재"
        return "conflict", f"동일 목표연도 기준 {direction} ({min(deltas):+,}~{max(deltas):+,})"
    return "changed_target", "목표연도가 달라 단순 비교 어려움. 의도된 변경인지 확인 필요."
```

**중요한 설계 철학**: 명세에서도 강조했듯, 이 도구의 가치는 정확도가 아니라 **"확인이 필요한 지점을 짚어주는 것"**. False positive(없는 충돌을 잡는 것)가 좀 있어도 False negative(실제 충돌을 놓치는 것)보다 훨씬 낫다. 실무자가 최종 판단을 하므로 Recall 우선.

### 8.2 효과 예시

**시나리오** — 과기정통부 주무관: 내일 배포할 "AI 인재양성 확대방안" 초안을 검증.

초안 일부:
> "정부는 AI 핵심인재 50만 명을 2027년까지 양성하고, 이를 위해 올해부터 5년간 총 4조 5천억원을 투입한다. 또한 지역 AI 특성화 대학을 기존 12개교에서 20개교로 확대한다."

호출:
```json
{
  "draft_text": "정부는 AI 핵심인재 50만 명을 2027년까지 양성하고, 이를 위해 올해부터 5년간 총 4조 5천억원을 투입한다. 또한 지역 AI 특성화 대학을 기존 12개교에서 20개교로 확대한다.",
  "context_window_months": 24,
  "ministry": "과학기술정보통신부"
}
```

가상 응답:
```json
{
  "extracted_claims": [
    { "claim": "AI 핵심인재 50만 명을 2027년까지",
      "metric": "AI 인재 양성 규모", "value": 500000, "unit": "명", "year_target": 2027 },
    { "claim": "5년간 총 4조 5천억원",
      "metric": "AI 인재양성 예산", "value": 4500000000000, "unit": "원", "year_target": null },
    { "claim": "지역 AI 특성화 대학 기존 12개교",
      "metric": "AI 특성화 대학 현재 규모", "value": 12, "unit": "개", "year_target": null },
    { "claim": "20개교로 확대",
      "metric": "AI 특성화 대학 확대 목표", "value": 20, "unit": "개", "year_target": null }
  ],
  "validations": [
    {
      "claim": "AI 핵심인재 50만 명을 2027년까지",
      "status": "conflict",
      "past_statements": [
        {
          "briefing_id": "156703118",
          "date": "2025-08-12",
          "ministry": "과학기술정보통신부",
          "statement": "AI 인재 30만 명을 2027년까지 양성",
          "delta": "+20만 명"
        }
      ],
      "suggestion": "8개월 전 같은 부처 발표 대비 목표치가 20만 명 증가했습니다. 상향 조정 근거(신규 예산, 위탁기관 확대 등)를 본문에 명시하거나 보도자료 도입부에서 조정 사실을 밝히는 것을 권장합니다."
    },
    {
      "claim": "5년간 총 4조 5천억원",
      "status": "new",
      "past_statements": [],
      "suggestion": null
    },
    {
      "claim": "지역 AI 특성화 대학 기존 12개교",
      "status": "conflict",
      "past_statements": [
        {
          "briefing_id": "156698445",
          "date": "2025-05-30",
          "ministry": "교육부",
          "statement": "AI 특성화 단과대학 15개교 지정 완료",
          "delta": "-3개교"
        }
      ],
      "suggestion": "교육부가 2025-05-30 발표에서 '15개교 지정 완료'라고 밝혔는데, 초안에는 '12개교'로 적혀 있습니다. 대학 정의(단과대/학과/특성화 사업 등)가 다를 수 있으니 교육부와 용어를 맞추거나 '과기정통부 지정 기준'임을 명시하세요."
    },
    {
      "claim": "20개교로 확대",
      "status": "new",
      "past_statements": [],
      "suggestion": null
    }
  ]
}
```

**이 결과가 주무관에게 주는 효과**:
1. "30만 → 50만"이 의도적 상향인지, 자료 착오인지 즉시 확인 가능
2. "12개교 vs 15개교" 같은 **부처간 정의 불일치**가 보도 배포 전에 걸림 — 이게 배포됐다면 다음날 오보 기사 감수 필요
3. 예산 4조 5천억은 신규 지표라 과거 발표와 비교 불가, 이 자체가 기자 질의 예상 포인트임을 미리 인지

**달라지는 것**: 이 도구 없이 같은 검증을 하려면 보도실 직원이 과거 2년치 관련 보도자료를 수기로 뒤져야 한다. 보통은 **그 작업이 생략**되어 엇박자가 배포된다. `validate_statistics`는 이 리스크를 기계적으로 잡아내는 거의 유일한 방법이고, 그래서 B2G 영업 훅으로 가장 강력하다.

---

## 9. 크로스커팅 이슈

8개 도구 모두에 공통적으로 적용되는 구현 주의사항.

### 9.1 한국어·부처명 처리

- **약칭-정식명 매핑**을 `ministry_alias` 테이블에 고정. 기재부↔기획재정부, 과기정통부↔과학기술정보통신부, 산자부↔산업통상자원부(단 "산자부"는 구 명칭 유의). 매핑은 시기별로도 달라서(예: 2023년 중소벤처기업부 명칭 유지/개편 논의), `valid_from`, `valid_to` 컬럼을 둔다.
- **숫자 표기 정규화**: "3조 2천억원", "32,000억원", "3.2조원"이 모두 같은 값. 적재 시 `normalize_kr_number()` 함수로 통합하고, 원문 표기는 `context` 필드에 보존.
- **연도 표기**: "2027년까지", "2027년말", "2027년 상반기"는 모두 `year_target=2027`로 묶되, 반기·분기 정보는 `period_detail` 서브필드로 보존.

### 9.2 에러 처리 및 관찰성

- 모든 도구는 공통 응답 래퍼 `{data, error, meta}` 구조 유지. `meta`에 검색에 소요된 ms, 조회된 레코드 수, 캐시 hit 여부를 포함해 Claude가 "이 답변이 얼마나 믿을 만한지" 메타 판단할 수 있게 한다.
- 도구별 p50/p95 지연 SLO: 1·2·6번 300ms / 3·4·7번 1s / 5번 2s / 8번 5s. 실서비스에서 초과 시 tail-latency 로그를 남기고 Qdrant 인덱스 샤드 조정.
- 빈 결과는 에러가 아니라 정상 응답이되 `hint` 필드에 "검색 범위를 넓혀보세요" 등 다음 행동을 제안(Claude가 자동으로 재시도하도록 유도).

### 9.3 보안·배포

- 공개 엔드포인트(fly.io 권장)로 깔 경우 rate limit: IP당 60req/min + Claude.ai 토큰 검증 bypass는 별도 allowlist.
- 원본 PDF·MD는 공개 GitHub에 두되, `statistics` 테이블은 서버에 private로 유지. 통계 테이블을 공개하면 경쟁 서비스가 재조립하기 쉬움.
- 스키마 변경은 도구별 `version` 필드로 관리. 같은 도구의 v1, v2를 동시 노출하고 6개월 deprecation 윈도우.

---

## 10. 구현 체크리스트

로드맵(명세 8단계)을 실제 작업 티켓 수준으로 쪼갠 체크리스트. "다음에 뭘 할까" 상태에서 바로 착수할 수 있는 granularity를 목표로 했다.

**Phase A — 데이터 기반 (1~2주차)**
- [ ] 디렉터리 구조·frontmatter 스펙 확정, Git 리포 초기화
- [ ] 정책브리핑 API 크롤러 (중앙부처 필터링 포함)
- [ ] Govpress 변환 엔진 연동 (이미 있음 — 파일 I/O 인터페이스만 정리)
- [ ] `briefings`, `briefing_ministries`, `ministry_alias` 테이블 DDL
- [ ] 적재 스크립트 `ingest.py` — idempotent, `--backfill 2021-01-01` 플래그 지원

**Phase B — 인덱스 (3주차)**
- [ ] FTS5 가상 테이블 + mecab-ko 기반 토크나이저 전처리
- [ ] Qdrant 컬렉션 생성, BGE-M3 배치 임베딩
- [ ] 청킹 로직 단위테스트 (특히 표·리스트 처리)
- [ ] 적재 파이프라인에 임베딩 자동 갱신 훅

**Phase C — 기본 도구 (4~5주차)**
- [ ] `search_briefing` (3개 모드)
- [ ] `get_briefing` + Redis 캐시
- [ ] `list_ministries_by_topic`
- [ ] MCP 서버 스캐폴딩 (Python `mcp` SDK), stdio·SSE 전송 둘 다 지원

**Phase D — 분석 도구 (6~7주차)**
- [ ] `trace_policy` + 키워드 확장 테이블
- [ ] `get_briefing_context`
- [ ] 벤치마크 세트 (30개 질의) 만들고 수동 평가

**Phase E — 비교·정정 (8~9주차)**
- [ ] `statistics` 테이블 + Haiku 기반 라벨링 배치
- [ ] `cross_check_ministries`
- [ ] `compare_versions` + git log 파서

**Phase F — 검증 도구 (10~12주차)**
- [ ] `extract_claims` 정규식·LLM 파이프라인
- [ ] `validate_statistics` end-to-end
- [ ] 실제 과기정통부 과거 보도자료 10건으로 false positive/negative 측정

**Phase G — 공개·연동 (13주차)**
- [ ] fly.io 배포 (SSE 엔드포인트)
- [ ] Claude Desktop 설치 가이드 README
- [ ] 킬러 기능 3종(`trace_policy`, `cross_check_ministries`, `validate_statistics`) 데모 GIF 제작
- [ ] GeekNews Show GN 게시

---

## 부록 A. 도구 호출 상호작용 매트릭스

Claude가 복합 질의를 받았을 때 도구를 어떤 순서로 호출하는지 패턴화한 참고표.

| 사용자 질의 유형 | 1차 호출 | 2차 호출 | 3차 호출 |
|---|---|---|---|
| "X 정책이 어떻게 변했나" | `trace_policy` | `get_briefing` (×2~3) | `cross_check_ministries` |
| "X 관련 최신 자료" | `search_briefing` | `get_briefing` | — |
| "X 주제로 부처간 이견 있나" | `list_ministries_by_topic` | `cross_check_ministries` | `get_briefing` |
| "이 자료 원래 뭐였지" | `compare_versions` | `get_briefing_context` | — |
| "내 초안 문제없나" | `validate_statistics` | `get_briefing` (충돌 후보) | — |
| "이 자료가 어떤 맥락인가" | `get_briefing` | `get_briefing_context` | `trace_policy` |

이 매트릭스는 프롬프트 엔지니어링 관점에서도 중요한데, MCP 서버 설명(tool description) 작성 시 위 패턴을 반영해 **"언제 쓰는지"** 를 Claude가 확실히 알 수 있게 해야 한다.

---

## 부록 B. 데모 시연 시나리오 (홍보용)

- **데모 1 — "디지털플랫폼정부 5년사"** (trace_policy): 1분 GIF. 질의 → 시계열 버블차트 → Claude 분석 내레이션.
- **데모 2 — "AI 인재 50만 vs 20만"** (cross_check_ministries): 30초 GIF. 기자 관점 훅.
- **데모 3 — "내 초안 체크"** (validate_statistics): 45초 GIF. 공공기관 실무자 관점 훅. 실제 과거 보도자료 샘플을 일부 수정해 초안처럼 만들어 시연.

GIF 3종을 README 상단에 순서대로 박으면 각기 다른 타깃 오디언스(정책연구자·기자·공무원)에게 한 번에 도달한다.
