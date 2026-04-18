# Govpress MCP

> **정책의 git log.** 중앙부처 보도자료 5년치를 Claude에게 맥락으로 먹이는 오픈소스 MCP 서버.
> 같은 정책의 연차별 후속 발표를 시계열로 묶고, 부처간 diff를 기계적으로 적발한다.

> ⚠️ **검증 대기 영역**: 아래 `compare_versions`(정정 diff) 기능은 중앙부처 보도자료의 정정·URL 덮어쓰기 빈도가 매우 낮다는 준우의 도메인 지식에 따라 존속 여부를 재검토 중입니다. [`silent-overwrite-검증실험.md`](silent-overwrite-검증실험.md)의 결정 트리가 완료되면 이 섹션이 확정됩니다. 현재 공식 킬러는 `trace_policy`와 `cross_check_ministries` 두 개입니다.

<!-- hero GIFs: 해당 파일을 docs/demo/*.gif 로 배포 -->
<p align="center">
  <img src="docs/demo/01-trace-policy.gif" width="720" alt="trace_policy demo — 디지털플랫폼정부 5년 추이"/>
  <br/><em>정책이 5년간 어떻게 변해왔는지 한 질문으로 추적</em>
</p>

<p align="center">
  <img src="docs/demo/02-cross-check.gif" width="720" alt="cross_check_ministries demo — AI 인재 50만 vs 20만"/>
  <br/><em>부처간 엇박자를 기계적으로 적발</em>
</p>

<p align="center">
  <img src="docs/demo/03-validate-stats.gif" width="720" alt="validate_statistics demo — 보도자료 초안 검증"/>
  <br/><em>내일 배포할 초안의 숫자가 과거 발표와 맞는지 사전 점검</em>
</p>

---

## 왜 만들었나

정부 보도자료는 누구나 볼 수 있다. 그런데 **5년치를 한꺼번에 읽는 사람은 아무도 없다.** 기자는 오늘치를 쓰고, 정책연구자는 연간보고서에 묶고, 공무원은 자기 과 것만 본다. 그 결과:

- 같은 정책의 숫자가 부처별로 다르게 돌아다닌다 ("AI 인재 50만 vs 20만")
- 목표 연도가 조용히 1년씩 밀려도 아무도 짚지 않는다
- 정정된 보도자료의 원래 문구는 공식 채널 어디에도 남지 않는다

**Govpress MCP**는 이 5년치 공공 자산을 Claude에게 통째로 컨텍스트로 넣어, 정책의 시계열·부처간 관계·정정 이력을 질문 한 줄로 꺼낼 수 있게 만든다.

## 핵심 기능 3종

### 1. `trace_policy` — 정책 변천사 추적

```
사용자: "디지털플랫폼정부 정책이 어떻게 발전해왔는지 분석해줘"

→ 2022: 비전 발표 단계 (과기정통부, 행안부 — 12건)
→ 2023: 예산 본격 편성 (+기재부 — 28건)
→ 2024: 마이데이터 2.0, AI 행정 (행안부 비중 역전 — 22건)
→ 2025: 집행 단계 (17건)
→ 2026: 성숙기 / 관심 이동? (8건)
```

건수 버블 + 부처 분포 히트맵 + 각 시기 대표 보도자료 3개를 Claude에게 넘기면, Claude가 "2024년에 주관 부처가 바뀐 이유"까지 자연스럽게 추론한다.

### 2. `cross_check_ministries` — 부처간 정책 대조

```
사용자: "AI 인재양성 관련 부처별 엇박자 없나 체크"

⚠️ number_mismatch
  · 과기정통부 (2025-08-12): AI 인재 50만 명 / 2027년까지
  · 교육부   (2025-09-03): 디지털·AI 인재 20만 명 / 2026년까지
```

기자 관점의 "특종거리 발굴" 도구. 의미 유사한 metric끼리 값이 다를 때 서버가 후보를 던지고, **진짜 충돌인지 판정은 Claude에게 맡긴다** (단위·시점·대상 정의 차이는 맥락이 필요하므로).

### 3. `validate_statistics` — 초안 숫자 사전 검증 (B2G)

```
초안: "AI 핵심인재 50만 명을 2027년까지 양성..."

⚠️ conflict
  이전 발표(2025-08-12, 같은 부처): "AI 인재 30만 명을 2027년까지"
  delta: +20만 명
  suggestion: 상향 조정 근거를 본문에 명시 권장
```

공공기관 실무자용. 내일 배포할 초안의 숫자 하나하나에 대해 과거 24개월 발표를 조회해 "확인 필요 지점"을 적시한다. **정확도보다 Recall을 우선** — 실제 충돌을 놓치느니 false positive가 낫다는 철학.

## 전체 도구 목록

| 도구 | 역할 | 주 호출자 |
|---|---|---|
| `search_briefing` | 키워드/시맨틱/하이브리드 검색 | 모든 사용자 |
| `get_briefing` | 본문 마크다운 조회 | 후속 도구 |
| `trace_policy` ⭐ | 5년 시계열 버킷팅 | 정책연구자 |
| `cross_check_ministries` ⭐ | 부처간 수치 대조 | 기자 |
| `compare_versions` 🧪 | 정정 전후 diff (*빈도 검증 대기*) | 기자·연구자 |
| `list_ministries_by_topic` | 주제별 부처 분포 | 진입 탐색 |
| `get_briefing_context` | 전후 맥락 조회 | 연구자 |
| `validate_statistics` ⭐ | 초안 숫자 검증 | 공공기관 |

## 데이터

- **범위**: 2021-04 ~ 2026-04 (5년치, 약 52,000건)
- **출처**: 중앙부처 보도자료 (기재부·산업부·과기정통부·환경부·교육부·국토부 등)
- **변환**: HWPX → Markdown (Govpress 변환 엔진 v0.3.x)
- **저장소**: [`policy-briefing-kr`](https://github.com/USER/policy-briefing-kr) (공개 Git 리포)
- **인덱스**: SQLite FTS5 + Qdrant (BGE-M3 임베딩, 청크 단위)

## 빠른 시작

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "govpress-mcp": {
      "command": "uvx",
      "args": ["govpress-mcp"]
    }
  }
}
```

Claude Desktop 재시작 후 채팅에서:
```
/mcp
→ govpress-mcp (8 tools available)
```

### 원격 엔드포인트 (Cloudflare Tunnel)

```
https://mcp.govpress.cloud/sse
```

SSE transport를 지원하는 클라이언트(Claude.ai custom connector 등)에서 바로 연결 가능.

### 로컬 개발

```bash
git clone https://github.com/USER/govpress-mcp
cd govpress-mcp
uv sync
uv run govpress-mcp --data-dir ~/policy-briefing-kr
```

## 아키텍처

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ korea.kr API │ ──> │ Govpress 엔진 │ ──> │ Markdown Git │
│  (크롤러)    │     │ (HWPX → MD)  │     │   (공개)     │
└──────────────┘     └──────────────┘     └──────┬───────┘
                                                 │
                    ┌────────────────────────────┼────────────┐
                    ▼                            ▼            ▼
            ┌───────────────┐          ┌─────────────┐  ┌──────────┐
            │ SQLite + FTS5 │          │   Qdrant    │  │  Redis   │
            │  (메타·통계)  │          │  (임베딩)   │  │ (캐시)   │
            └───────┬───────┘          └──────┬──────┘  └────┬─────┘
                    │                          │              │
                    └──────────┬───────────────┴──────────────┘
                               ▼
                      ┌────────────────┐
                      │ Govpress MCP 서버│
                      │  (Python mcp)  │
                      └────────┬───────┘
                               │ stdio / SSE
                               ▼
                      ┌────────────────┐
                      │     Claude     │
                      └────────────────┘
```

자세한 설계는 [`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md) 참조.

## 로드맵

- [x] 데이터 적재 파이프라인 (Phase A)
- [x] 메타데이터 DB + FTS 인덱스 (Phase B)
- [x] `search_briefing`, `get_briefing`, `list_ministries_by_topic` (Phase C)
- [x] Qdrant 벡터 인덱스 + `trace_policy`, `get_briefing_context` (Phase D)
- [ ] `statistics` 테이블 + `cross_check_ministries` (Phase E — 진행 중)
- [ ] `compare_versions` (Phase F) — **silent-overwrite 실험 결과에 따라 제거·유지·승격 결정**
- [ ] `validate_statistics` (Phase G)
- [ ] fly.io 공개 엔드포인트 (Phase H)

체크리스트 상세는 [`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md) §10.

## FAQ

**Q. 지자체·공기업 보도자료도 포함되나요?**
A. 초기 버전은 중앙부처만. 추후 확장 예정.

**Q. 기존 정책브리핑 검색과 뭐가 다른가요?**
A. 정책브리핑은 "오늘의 보도자료"를 빠르게 찾게 해준다. Govpress MCP는 "5년간 어떻게 변했는지"를 한 질문으로 받게 한다. 전혀 다른 축의 도구다.

**Q. 숫자 충돌 탐지가 오탐이 많지 않나요?**
A. 많다. 의도된 설계다. 충돌 판정은 실무자/Claude가, 후보 적시는 서버가 담당한다. Recall 우선.

**Q. 보도자료 원본이 정정되면 어떻게 알 수 있나요?**
A. 적재 파이프라인에서 sha256 해시를 매일 비교해 변경을 Git commit으로 기록한다. 다만 중앙부처 보도자료는 공식 정정·URL 덮어쓰기 자체가 드문 것으로 관측되어, `compare_versions` 도구를 킬러로 내세울 만큼 자주 트리거되는지는 [현재 검증 중](silent-overwrite-검증실험.md)이다.

**Q. 왜 Claude 전용인가요?**
A. 전용 아니다. MCP 표준 스펙이므로 MCP 지원 클라이언트라면 모두 동작한다. 다만 실제 검증은 Claude Desktop·Claude Code 위주.

## 라이선스

- 코드: MIT
- 데이터(마크다운 변환물): CC BY 4.0 (원문 저작권은 각 부처)

## 기여

`good first issue` 라벨 참조. 부처명 alias 보강, 새 통계 패턴 추가, 도구별 벤치마크 질의 세트 확장 환영.

---

Made by [@USER](https://github.com/USER) · 관련 글: [왜 정책 보도자료의 git blame이 필요한가](docs/blog/why-policy-git-blame.md)
