# Phase 2 Report

완료 일시: `2026-04-22`

## Summary

Phase 2의 T1~T4는 완료되었습니다.

- T1: Warm Markdown corpus를 Hot index로 변환
- T2: Qdrant + TEI + Redis 스택 구성
- T3: MCP 8개 도구 구현
- T4: Cloudflare Tunnel을 통한 외부 공개

## T1 — derive_hot

결과:

- corpus md files: `130,012`
- indexed docs: `129,934`
- unindexed docs: `78`
- qdrant points: `454,125`
- briefing_fts rows: `454,125`
- tokenizer: `unicode61 trigram`

복구 런 성능:

- processed md files: `4,085`
- total chunks: `11,108`
- wall clock: `2,113.00s`
- docs/min: `116.0`
- chunks/min: `315.4`

관련 문서:

- [`derive-hot-report.md`](derive-hot-report.md)
- [`derive-hot-benchmark.md`](derive-hot-benchmark.md)

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

확인:

- Qdrant health: `/healthz`
- TEI health: `/health`
- Redis ping: `PONG`

## T3 — MCP 8 Tools

구현 완료 도구:

1. `get_stats`
2. `get_briefing`
3. `list_briefings`
4. `fts_search`
5. `search_briefing`
6. `cross_check_ministries`
7. `trace_policy`
8. `compare_versions`

특이사항:

- `compare_versions`는 `experimental` 스텁으로 제공
- 모든 도구는 응답 크기 `50 KB` 미만 기준으로 테스트
- `tests/test_mcp_tools.py` 8개 통과

## T4 — Cloudflare Tunnel

결과:

- hostname: `mcp.govpress.cloud`
- origin: `http://127.0.0.1:8001`
- path: `/mcp`
- tunnel status: `healthy`
- external tools/list: `8`

systemd:

- `govpress-mcp-server.service`
- `govpress-mcp-cloudflared.service`

두 서비스 모두 `enabled`, `active`.

관련 문서:

- [`t4-cloudflare-report.md`](t4-cloudflare-report.md)

## Final Index State

- indexed docs: `129,934`
- qdrant chunks: `454,125`
- FTS5 rows: `454,125`

## 미완료·보류

- task #32: HWPX `249`건 재시도 보류
- `compare_versions`: `checksums_history` 누적 후 활성화
- `derive_hot --incremental`: daily service 연동 필요

## Phase 3 후보

- kordoc DRM (`52`건)
- mecab-ko 실험

