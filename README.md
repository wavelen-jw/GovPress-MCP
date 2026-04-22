# Govpress MCP

정책브리핑 보도자료를 장기 보존형 Markdown으로 변환하고, 벡터·키워드 색인을 구축해 MCP 8개 도구로 제공하는 서버입니다.

[`Phase 1 Report`](docs/phase1-report.md) · [`Phase 2 Report`](docs/phase2-report.md) · [`T1 Derive Hot Report`](docs/derive-hot-report.md) · [`T4 Cloudflare Report`](docs/t4-cloudflare-report.md) · [`LICENSE-data`](LICENSE-data)

## 프로젝트 개요

- 범위: 정책브리핑 `129,901`건, `2021-04 ~ 현재`
- 적재: 일일 증분 timer 운영 중
- 변환: `HWPX -> Markdown`
- 색인: `BGE-M3` 임베딩 + `Qdrant` + `SQLite FTS5`
- 서빙: `FastMCP` 기반 MCP 서버, 외부 엔드포인트 `https://mcp.govpress.cloud/mcp`

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
| `list_briefings` | 날짜·부처·엔터티·포맷 필터 목록 | `date_from`, `date_to`, `department`, `entity_type`, `source_format`, `page`, `page_size` |
| `fts_search` | SQLite FTS5 키워드 검색 | `query`, `limit` |
| `search_briefing` | Qdrant + BGE-M3 의미 검색 | `query`, `date_from`, `date_to`, `ministry`, `limit` |
| `cross_check_ministries` | 동일 주제에 대한 부처별 대표 문서 비교 | `topic`, `date_from`, `date_to`, `min_ministries` |
| `trace_policy` | 정책 흐름 시계열 추적 | `keyword`, `date_from`, `date_to` |
| `compare_versions` | 개정 전후 비교 스텁 | `briefing_id`, `revision` |

## 사용 예시

```text
Claude: "탄소중립 정책 흐름을 2021년부터 시계열로 정리해줘."
-> trace_policy("탄소중립")
```

```text
Claude: "AI 인재양성 관련 부처별 입장 차이를 비교해줘."
-> cross_check_ministries("AI 인재양성")
```

```text
Claude: "기후위기 적응 관련 최신 보도자료 5건만 찾아줘."
-> search_briefing("기후위기 적응")
-> list_briefings(...)
```

## 데이터

- 출처: 공공데이터포털 정책브리핑 API
- 데이터 라이선스: 공공누리 1유형 (출처표시)
- 코드 라이선스: MIT
- 라이선스 고지 파일: [`LICENSE-data`](LICENSE-data)

현재 기준:

- Markdown corpus: `129,901`
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

## Phase 2 현황

- T1: `derive_hot.py` 완료
  - 색인 완료 `129,934`
  - 청크 `454,125`
  - FTS5 rows `454,125`
- T2: `docker-compose` 스택 완료
  - `qdrant`, `tei`, `redis`
- T3: MCP 도구 8개 구현 완료
- T4: `mcp.govpress.cloud` 외부 공개 완료

상세 보고:

- [`docs/phase2-report.md`](docs/phase2-report.md)
- [`docs/derive-hot-benchmark.md`](docs/derive-hot-benchmark.md)
- [`docs/derive-hot-report.md`](docs/derive-hot-report.md)
- [`docs/t4-cloudflare-report.md`](docs/t4-cloudflare-report.md)
- [`docs/reconvert-report.md`](docs/reconvert-report.md)

## 개발 메모

- 작업 루트: `/home/wavel/projects/govpress-mcp`
- 데이터 루트: `/home/wavel/projects/govpress-mcp/data`
- WSL 네이티브 경로만 사용, `/mnt/c/...` 금지

