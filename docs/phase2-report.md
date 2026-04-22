# Phase 2 Report

완료 일시: `2026-04-22`

## 요약

Phase 2는 Warm Markdown corpus를 Hot 검색 레이어와 공개 MCP 서버로 연결하는 단계였다.  
결과적으로 `mcp.govpress.cloud`에서 읽기 전용 MCP 7개 도구를 공개 운영할 수 있는 상태가 되었다.

## T1 — derive_hot

- corpus md files: `130,012`
- indexed docs: `129,934`
- unindexed docs: `78`
- qdrant chunks: `454,125`
- briefing_fts rows: `454,125`
- tokenizer: `unicode61 trigram`

복구 런 성능:

- processed md files: `4,085`
- total chunks: `11,108`
- wall clock: `2,113.00s`
- docs/min: `116.0`
- chunks/min: `315.4`

관련 문서:

- [derive-hot-report.md](derive-hot-report.md)
- [derive-hot-benchmark.md](derive-hot-benchmark.md)

## T2 — Docker Compose Stack

구성:

- `qdrant`
- `tei` (`http://localhost:18080`)
- `redis`
- `mcp-server` 플레이스홀더 구성

운영 조건:

- 모든 볼륨은 `/home/wavel/projects/govpress-mcp/data` 하위
- 네트워크: `govpress_mcp_net`
- Redis: `maxmemory 1gb`, `allkeys-lru`

## T3 — MCP Tools

공개 도구:

1. `get_stats`
2. `get_briefing`
3. `list_briefings`
4. `fts_search`
5. `search_briefing`
6. `cross_check_ministries`
7. `trace_policy`

비공개/보류:

- `compare_versions`
  - `checksums_history` 누적 전까지 공개 액션 목록에서 숨김

특이사항:

- 모든 공개 도구는 읽기 전용으로 메타데이터 설정
- 응답 크기 `50 KB` 미만 기준으로 테스트
- `tests/test_mcp_tools.py` 통과

## T4 — Cloudflare Tunnel

- hostname: `mcp.govpress.cloud`
- origin: `http://127.0.0.1:8001`
- path: `/mcp`
- tunnel status: `healthy`
- external tools/list: `7`

systemd:

- `govpress-mcp-server.service`
- `govpress-mcp-cloudflared.service`

두 서비스 모두 `enabled`, `active`

관련 문서:

- [t4-cloudflare-report.md](t4-cloudflare-report.md)

## 최종 색인 상태

- indexed docs: `129,934`
- qdrant chunks: `454,125`
- FTS5 rows: `454,125`

## 미완료·보류

- task #32: HWPX `249`건 재시도 대기
  - `govpress-converter` 파서 개선 릴리즈 후 재실행
- `compare_versions`
  - `checksums_history` 누적 후 활성화
- `derive_hot --incremental`
  - daily service 연동 필요

## Phase 3 후보

- kordoc DRM (`52`건)
- mecab-ko 실험

