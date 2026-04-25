# Govpress MCP

정책브리핑 보도자료를 장기 보존형 Markdown으로 변환하고, 벡터·키워드 색인을 구축해 MCP로 제공하는 공개 서버입니다.

[Phase 1 Report](docs/phase1-report.md) · [Phase 2 Report](docs/phase2-report.md) · [Backfill Expansion Probe](docs/backfill-expansion-probe.md) · [T1 Derive Hot Report](docs/derive-hot-report.md) · [T4 Cloudflare Report](docs/t4-cloudflare-report.md) · [LICENSE-data](LICENSE-data)

## 프로젝트 개요

- 범위: 정책브리핑 보도자료 `130,012`건
- 기간: `2021-04` ~ 현재
- 수집 방식: 1회 전량 백필 + 일일 증분
- 변환: `HWPX -> Markdown`
- 색인: `BGE-M3` 임베딩 + `Qdrant` + `SQLite FTS5`
- 서빙: `FastMCP`
- 공개 엔드포인트: `https://mcp.govpress.cloud/mcp`

## MCP 연결 방법

### 1. Claude Desktop (`mcp.json`)

```json
{
  "mcpServers": {
    "govpress": {
      "url": "https://mcp.govpress.cloud/mcp"
    }
  }
}
```

### 2. ChatGPT Custom Connector

- URL: `https://mcp.govpress.cloud/mcp`

### 3. Codex CLI

```bash
codex mcp add https://mcp.govpress.cloud/mcp
```

## 도구 목록

| 도구명 | 설명 | 주요 파라미터 |
|---|---|---|
| `get_stats` | 코퍼스·색인 현황 집계 | 없음 |
| `get_briefing` | 단건 Markdown 전문 조회 | `id`, `include_metadata`, `max_chars` |
| `list_briefings` | 날짜·부처·기관유형·포맷 필터 목록 | `date_from`, `date_to`, `department`, `entity_type`, `source_format`, `page`, `page_size` |
| `fts_search` | 본문 키워드 검색 | `query`, `limit` |
| `search_briefing` | 의미 기반 유사 문서 검색 | `query`, `date_from`, `date_to`, `ministry`, `limit` |
| `cross_check_ministries` | 같은 주제에 대한 부처별 대표 문서 비교 | `topic`, `date_from`, `date_to`, `min_ministries` |
| `trace_policy` | 정책 흐름 시계열 추적 | `keyword`, `date_from`, `date_to` |

## 사용 예시

```text
디지털플랫폼정부 정책이 2022년부터 2026년까지 어떻게 바뀌었는지 설명해줘.
```

```text
AI 인재양성에 대해 부처별로 목표 숫자나 표현 차이가 있는지 비교해줘.
```

```text
기후위기 적응 관련 최신 보도자료 5건을 핵심만 요약해줘.
```

더 많은 질문 예시는 [docs/mcp-question-examples.md](docs/mcp-question-examples.md)에서 볼 수 있습니다.

## 빠른 테스트

- 도구 호출 예시: [docs/mcp-test-examples.md](docs/mcp-test-examples.md)
- 질문 예시: [docs/mcp-question-examples.md](docs/mcp-question-examples.md)

대표 확인 항목:

- `tools/list == 7`
- `get_stats.doc_count == 130012`
- `search_briefing("탄소중립")` 결과 1건 이상
- `trace_policy("디지털플랫폼정부")` 결과 1건 이상

## 데이터

- 출처: 공공데이터포털 정책브리핑 API
- 데이터 라이선스: 공공누리 1유형 (출처표시)
- 코드 라이선스: MIT
- 데이터 고지: [LICENSE-data](LICENSE-data)

## 확장 정찰

정책브리핑 API 제공 시작일(`1999-02-18`)부터 현재 백필 기준일(`2026-04-18`)까지 metadata-only 정찰을 완료했습니다. 상세 통계는 [docs/backfill-expansion-probe.md](docs/backfill-expansion-probe.md), SQLite 적재·대조 결과는 [docs/probe-metadata-load-report.md](docs/probe-metadata-load-report.md), manifest 계획과 생성 결과는 [docs/backfill-manifest-plan.md](docs/backfill-manifest-plan.md), [docs/backfill-manifest-report.md](docs/backfill-manifest-report.md)에 보관합니다. 1차 실행 결과는 [docs/expanded-backfill-batch1-report.md](docs/expanded-backfill-batch1-report.md)에 보관합니다.

- 대상 날짜: `9,922`일
- 성공 날짜: `9,915`일
- 총 문서: `457,609`건
- 우선 포맷 추정: `hwpx 103,102` / `hwp 280,256` / `pdf 6,140`
- unique 문서ID: `439,727`건
- 현재 수집 완료: `129,901`건
- 추가 후보: `hwp 237,102` / `hwpx 339` / `pdf 5,162`
- 1차 배치 결과: API 본문 `865`건 MD 생성, HWP `108`건 MD 반영, HWP COM 산출 누락 `52`건, HWPX/PDF 변환 실패 `71`건 보류
- 본문 포함 item metadata: `data/fetch-log/probe-items-19990218-20260418-v5.jsonl` 로컬 보관, Git 제외
- 저장공간 정책: HWP는 HWPX 변환 및 MD 생성 성공 후 원본 `.hwp` 삭제 가능. raw 장기 보관은 별도 로컬 드라이브로 이동

## API와 MCP의 차이

정책브리핑 API는 날짜별 문서 목록, 기본 메타, 첨부파일 URL을 제공하는 수준이다.  
Govpress MCP는 여기에 Markdown 변환, 본문 색인, 의미 검색, 부처 비교, 정책 흐름 추적을 추가한 읽기 전용 서비스다.

- API 직래핑에 바로 적합한 기능: `list_briefings`
- 부분적으로만 가능한 기능: 축소형 `get_briefing`
- 색인 레이어가 필요한 기능: `fts_search`, `search_briefing`, `cross_check_ministries`, `trace_policy`, `get_stats`

상세 설명은 [docs/api-vs-mcp.md](docs/api-vs-mcp.md)에서 볼 수 있습니다.

현재 기준:

- Markdown corpus: `130,012`
- `source_format=hwpx`: `128,884`
- `source_format=hwp`: `53`
- `source_format=pdf`: `1,025`
- 색인 완료 문서: `129,934`
- 색인 청크: `454,125`
- FTS5 rows: `454,125`

## 기술 스택

- Qdrant
- BGE-M3
- SQLite FTS5
- Redis
- Cloudflare Tunnel
- FastMCP

## 운영 점검

MCP 사용 현황은 로컬 대시보드에서 확인할 수 있습니다.

- HTML 대시보드: `http://127.0.0.1:8001/dashboard`
- JSON 요약: `http://127.0.0.1:8001/dashboard/usage.json`
- 원본 로그: `data/fetch-log/mcp-usage.jsonl`

기록 항목:

- 호출 시각
- 도구명
- 인자
- 응답 크기
- 지연 시간
- record_count
- cache_hit
- 성공/실패 상태

## 문서

- [Phase 1 Report](docs/phase1-report.md)
- [Phase 2 Report](docs/phase2-report.md)
- [Backfill Expansion Probe](docs/backfill-expansion-probe.md)
- [Probe Metadata Load Report](docs/probe-metadata-load-report.md)
- [Backfill Manifest Plan](docs/backfill-manifest-plan.md)
- [Backfill Manifest Report](docs/backfill-manifest-report.md)
- [Expanded Backfill Batch 1 Report](docs/expanded-backfill-batch1-report.md)
- [T1 Derive Hot Report](docs/derive-hot-report.md)
- [T1 Derive Hot Benchmark](docs/derive-hot-benchmark.md)
- [T4 Cloudflare Report](docs/t4-cloudflare-report.md)
- [API vs MCP](docs/api-vs-mcp.md)
- [MCP Test Examples](docs/mcp-test-examples.md)
- [MCP Question Examples](docs/mcp-question-examples.md)

## 개발 메모

- 작업 루트: `/home/wavel/projects/govpress-mcp`
- 데이터 루트: `/home/wavel/projects/govpress-mcp/data`
- WSL 네이티브 경로만 사용
- `/mnt/c/...` 경로 사용 금지
