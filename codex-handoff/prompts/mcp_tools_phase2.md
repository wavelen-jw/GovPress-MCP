# T3 작업 프롬프트 — MCP 8개 도구 구현

**이 프롬프트는 T2(Qdrant/TEI 임베딩) 완료 + 사람 승인 후에만 Codex에 주입한다.**

---

## 사전 확인 (착수 전 반드시 실행)

```bash
# T1 완료 확인
sqlite3 /home/$USER/govpress-mcp/data/govpress.db   "SELECT name FROM sqlite_master WHERE type='table'" | sort

# 필수 테이블: briefings, briefing_ministries, ministry_alias, statistics, briefings_fts(virtual)

# T2 완료 확인
curl -s http://localhost:6333/healthz | python3 -m json.tool
curl -s http://localhost:6333/collections/briefing_chunks | python3 -m json.tool
# vectors_count > 0 이어야 함

# 인프라 상태
docker compose ps
# qdrant, embed, redis 모두 healthy
```

하나라도 실패하면 **착수 금지** — 사람에게 T1/T2 완료 확인 요청.

---

## 작업 지시

AGENTS.md §1~§8을 먼저 읽고 불변 조건 전부 준수. 특히 §8.2 포트 설정:
- Qdrant 헬스 체크: `/healthz` (Qdrant 1.17.1 기준)
- TEI 외부 포트: `18080`

### 1. 프로젝트 스캐폴딩

```
src/govpress_mcp/
├── server.py          # MCP 서버 진입점 (stdio + SSE 양쪽 지원)
├── tools/
│   ├── __init__.py
│   ├── search.py      # search_briefing
│   ├── fetch.py       # get_briefing
│   ├── trace.py       # trace_policy
│   ├── cross.py       # cross_check_ministries
│   ├── versions.py    # compare_versions
│   ├── topic.py       # list_ministries_by_topic
│   ├── context.py     # get_briefing_context
│   └── validate.py    # validate_statistics + extract_claims (8번 도구)
├── db/
│   ├── __init__.py
│   ├── sqlite.py      # SQLite + FTS5 쿼리
│   ├── qdrant.py      # Qdrant 클라이언트 래퍼
│   └── redis_cache.py # Redis LRU 캐시
└── common.py          # 공통 응답 래퍼 {data, error, meta}
```

Python MCP SDK: `pip install mcp`. stdio와 SSE transport 둘 다 지원해야 한다.

### 2. 공통 응답 래퍼

모든 도구 응답은 아래 구조를 준수한다:

```python
@dataclass
class ToolResponse:
    data: dict | list | None
    error: str | None = None
    meta: dict = field(default_factory=dict)
    # meta 필수 키: latency_ms, record_count, cache_hit
```

### 3. 8개 도구 구현 스펙

#### 도구 1: search_briefing

```python
async def search_briefing(
    query: str,
    date_from: str | None = None,   # ISO 8601
    date_to: str | None = None,
    ministry: str | None = None,
    limit: int = 10,
    mode: Literal["keyword", "semantic", "hybrid"] = "keyword",
) -> ToolResponse
```

- `keyword`: FTS5 `briefings_fts` MATCH 쿼리
- `semantic`: Qdrant 벡터 검색 (컬렉션 `briefing_chunks`)
- `hybrid`: RRF(Reciprocal Rank Fusion, k=60)로 keyword + semantic 결합
- ministry 필터는 `ministry_alias` 테이블로 약칭도 매칭 (`기재부` → `기획재정부`)
- 청크 단위 hit를 briefing 단위로 집계 (같은 briefing_id는 최고 score만)
- score 0~1 min-max 정규화

SLO: p50 < 300ms

#### 도구 2: get_briefing

```python
async def get_briefing(
    id: str,
    include_metadata: bool = True,
    max_chars: int | None = None,
) -> ToolResponse
```

- Redis LRU 캐시 우선 조회 (TTL 1시간, 최대 500건)
- 미스 시 파일 시스템에서 MD 파일 읽기 (`data/md/{yyyy}/{mm}/{id}.md`)
- `max_chars` 초과 시 마지막 `##`/`###` 경계 기준으로 `smart_truncate`
  - 잘린 위치 마커 추가: `

[...이하 생략 (총 N자 중 M자)...]
`
- frontmatter는 `include_metadata=True`일 때만 응답에 포함

SLO: p50 < 300ms

#### 도구 3: trace_policy

```python
async def trace_policy(
    keyword: str,
    date_from: str | None = None,   # 기본: 오늘 - 5년
    date_to: str | None = None,     # 기본: 오늘
    granularity: Literal["year", "quarter", "month"] = "year",
) -> ToolResponse
```

- 키워드 확장: `policy_aliases` 테이블 (없으면 건너뜀)
- Qdrant top_k=500으로 광범위 semantic search
- 버킷팅 후 버킷별 centroid 계산 → 중심에 가장 가까운 3개 대표 문서 선정
- `summary_hint: null` — Claude가 채우도록 의도적으로 비움
- `ministry_evolution` 딕셔너리: `{부처명: [연도별 건수]}`

SLO: p50 < 1s

#### 도구 4: cross_check_ministries

```python
async def cross_check_ministries(
    topic: str,
    date_from: str | None = None,   # 기본: 오늘 - 1년
    date_to: str | None = None,
    min_ministries: int = 2,
) -> ToolResponse
```

- Qdrant top_k=200 semantic search → 부처별 그룹핑
- 부처별 상위 5건에서 `statistics` 테이블의 핵심 수치 추출
- `detect_conflicts`: metric 임베딩 유사도 > 0.85이면 같은 지표 클러스터로 묶음
- 충돌 타입: `number_mismatch` / `unit_mismatch`
- 서버는 충돌 **후보만** 제시. 실제 충돌 여부 판단은 Claude 몫

SLO: p50 < 1s

#### 도구 5: compare_versions

```python
async def compare_versions(
    briefing_id: str,
    revision: int | None = None,    # None이면 전체 이력
) -> ToolResponse
```

- `data/md/` 하위 Git 리포 `git log --follow` + `git show`로 리비전 추출
- commit 메시지 규약: `correction: {id} r{n}` → 리비전 카운트
- `meta: ...` 접두 커밋은 리비전에서 제외
- diff 150줄 초과 시 hunk 단위 요약 + `... (N lines snipped) ...`
- `summary`는 `revision_summaries` 테이블에서 조회 (적재 시 사전 생성)

SLO: p50 < 2s

#### 도구 6: list_ministries_by_topic

```python
async def list_ministries_by_topic(
    query: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> ToolResponse
```

- Qdrant top_k=1000으로 후보 briefing_id 수집
- SQL: `briefing_ministries` 테이블 JOIN으로 부처별 집계
- 공동발표 보도자료는 관련 부처 모두에 카운트
- 응답: `[{name, count, first_date, last_date}]` 내림차순

SLO: p50 < 300ms

#### 도구 7: get_briefing_context

```python
async def get_briefing_context(
    id: str,
    window: int = 6,               # ±개월
) -> ToolResponse
```

- 대상 문서의 Qdrant 임베딩 조회
- 시간 윈도우 내 preceding/following 후보 → cosine similarity ≥ 0.75인 것 top-5
- `relation: null` — Claude가 단계 라벨 붙이도록 의도적으로 비움
- `related_topics`: `briefings.tags` 컬럼 (없으면 빈 리스트)

SLO: p50 < 1s

#### 도구 8: validate_statistics (+ extract_claims 내장)

```python
async def validate_statistics(
    text: str,                     # 검증할 초안 또는 보도자료 본문
    date_window: int = 24,         # 비교 기준 ±개월
) -> ToolResponse
```

내부 2단계:

1. `extract_claims(text)`: 정규식으로 수치 후보 추출 → Claude Haiku로 metric/value/unit/year_target 라벨링
2. 각 claim을 `statistics` 테이블 및 Qdrant와 대조 → `conflicts` 리스트 생성

`conflicts` 항목: `{claim, our_value, their_value, source_id, conflict_type}`

설계 원칙: **Recall 우선** (False negative가 False positive보다 위험). 충돌 후보를 넉넉히 제시.

SLO: p50 < 5s

### 4. MCP 서버 구성 (server.py)

```python
from mcp.server import Server
from mcp.server.stdio import stdio_server

app = Server("govpress-mcp")

@app.list_tools()
async def list_tools(): ...

@app.call_tool()
async def call_tool(name, arguments): ...

# stdio 모드 (Codex/Claude Desktop 연동)
async def main():
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())

# SSE 모드 (웹 클라이언트 연동) — 별도 엔트리포인트
```

`pyproject.toml` 엔트리포인트:
```toml
[project.scripts]
govpress-mcp = "govpress_mcp.server:main_stdio"
govpress-mcp-sse = "govpress_mcp.server:main_sse"
```

### 5. 테스트

- `tests/test_search.py` — keyword/semantic/hybrid 세 모드, 빈 결과 케이스
- `tests/test_get_briefing.py` — max_chars truncation, Redis cache hit/miss
- `tests/test_trace_policy.py` — 버킷팅 정확도, summary_hint null 확인
- `tests/test_cross_check.py` — 충돌 탐지 (값 다른 케이스 / 같은 케이스)
- `tests/test_validate_stats.py` — extract_claims 정규식 패턴 8종
- 전체: `pytest -q` 통과 필수

### 6. MCP 설정 파일 (Claude Desktop 연동용)

`mcp-config.example.json`:
```json
{
  "mcpServers": {
    "govpress": {
      "command": "python",
      "args": ["-m", "govpress_mcp.server"],
      "env": {
        "QDRANT_URL": "http://localhost:6333",
        "EMBED_URL": "http://localhost:18080",
        "REDIS_URL": "redis://localhost:6379",
        "GOVPRESS_DB_PATH": "/home/USER/govpress-mcp/data/govpress.db",
        "GOVPRESS_MD_ROOT": "/home/USER/govpress-mcp/data/md"
      }
    }
  }
}
```

---

## T3 완료 조건 (전부 ✅ 될 때까지 종료 금지)

- [ ] 8개 도구 전부 구현 완료 + `@app.call_tool()` 등록
- [ ] `pytest -q` 전체 통과 (Phase 1 테스트 포함)
- [ ] Claude Desktop에서 `govpress-mcp` 서버 연결 후 `search_briefing` 도구 호출 성공
- [ ] SLO 검증: search_briefing hybrid 모드 p50 < 300ms (샘플 10회 평균)
- [ ] 공통 응답 래퍼 `{data, error, meta}` 전 도구 적용 확인
- [ ] `mcp-config.example.json` 작성 완료
- [ ] 서비스키/API 키가 커밋·로그에 노출되지 않음 (전수 grep)

---

## T3 완료 보고 형식

```
T3 완료. MCP 8개 도구 구현 성공. 사람 검수 대기.
- 도구: search_briefing / get_briefing / trace_policy / cross_check_ministries /
        compare_versions / list_ministries_by_topic / get_briefing_context / validate_statistics
- 테스트: N/N pass
- SLO: search_briefing hybrid p50 = Xms
- Claude Desktop 연결: 성공
사람이 도구를 직접 호출해보고 "Phase 2 완료" 또는 수정 지시를 내려주세요.
```

---

## 절대 하지 말 것 (Phase 2 추가 제약)

- Qdrant 헬스 체크를 `/health`로 보내는 것 (→ `/healthz` 사용)
- TEI를 `8080` 포트로 연결 (→ `18080` 사용)
- `statistics` 테이블 없이 validate_statistics 구현 (T1 선행 필수)
- 실시간 LLM 라벨링을 validate_statistics 내부에서 호출 (비용 폭주). 라벨은 적재 시 사전 생성된 것만 조회
- MCP SDK 없이 직접 JSON-RPC 구현 (유지보수 불가)
