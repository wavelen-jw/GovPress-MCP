# GovPress MCP 1999~2021 확장 정찰 패스 지시서

## 목표

- 정책브리핑 API가 `1999-02-18`부터 제공된다는 전제하에, 현재 5년치 이전 구간을 전량 다운로드하기 전에 metadata-only 정찰을 수행한다.
- 대상 범위: `1999-02-18 ~ 2021-04-17`
- 다운로드, 변환, 색인은 절대 하지 않는다.
- API `list_items(date)`만 호출해 연도별 문서 수와 첨부 포맷 분포를 산출한다.

## 작업 위치

- 서버: 서버W
- repo: `/home/wavel/projects/govpress-mcp`
- data root: `/home/wavel/projects/govpress-mcp/data`
- `/mnt/c/...` 경로 사용 금지

## 사전 확인

- `.env` 또는 환경변수에 `GOVPRESS_POLICY_BRIEFING_SERVICE_KEY`가 있어야 한다.
- `api2.govpress.cloud` 호출 금지.
- `apis.data.go.kr` 정책브리핑 API만 호출.
- rate limit 유지:
  - 요청 간 최소 `0.3s`
  - `429`/`503` exponential backoff
  - User-Agent: `govpress-mcp-bulk/1.0 (+https://mcp.govpress.cloud)`

## 구현

새 CLI를 추가한다.

```bash
python -m govpress_mcp.probe_backfill
```

옵션:

- `--date-range YYYY-MM-DD..YYYY-MM-DD`
- `--data-root PATH` 기본값 `data/`
- `--log-json PATH` 기본값 `data/fetch-log/probe-YYYYMMDD-HHMMSS.jsonl`
- `--report PATH` 기본값 `docs/backfill-expansion-probe.md`
- `--resume` 기존 `log-json`이 있으면 완료 날짜 skip
- `--sample-days N` 선택 시 앞에서 N일만 테스트

## 동작

- 각 날짜에 대해 `PolicyBriefingClient.list_items(target_date)`만 실행한다.
- `item.attachments`를 훑어서 확장자 분포를 집계한다.
- 다음 호출은 금지한다.
  - `client.download_item_hwpx()`
  - `client.download_attachment()`
  - `convert_hwpx()`
  - `convert_pdf()`

날짜별 JSONL 기록:

```json
{
  "event": "date_summary",
  "target_date": "YYYY-MM-DD",
  "item_count": 0,
  "extension_counts": {
    ".hwpx": 0,
    ".hwp": 0,
    ".pdf": 0,
    ".odt": 0,
    "none": 0,
    "other": 0
  },
  "selected_format_counts": {
    "hwpx": 0,
    "hwp": 0,
    "pdf": 0,
    "odt_only": 0,
    "no_attachments": 0,
    "other": 0
  },
  "error": null
}
```

- 실패 날짜는 `error` 필드에 기록하고 다음 날짜를 계속 진행한다.
- 60초마다 stdout heartbeat를 출력한다.
  - `current_date`
  - `completed_days`
  - `rate_days_per_min`
  - `total_items_so_far`

## 집계 보고서

`docs/backfill-expansion-probe.md`를 작성한다.

포함 항목:

- 대상 범위와 총 날짜 수
- 전체 문서 수
- 연도별 문서 수
- 연도별 첨부 확장자 분포
- 연도별 최우선 포맷 추정
- 실패 날짜 목록
- 현재 5년 실측 대비 확장 배율
- 예상 raw 용량 범위
- 예상 HWP COM 변환 대상 규모
- 예상 처리 소요시간
- 권장 백필 순서

## 실행 절차

1. 샘플 3일 검증

```bash
python -m govpress_mcp.probe_backfill \
  --date-range 2021-04-18..2021-04-20 \
  --data-root /home/wavel/projects/govpress-mcp/data \
  --log-json data/fetch-log/probe-sample.jsonl \
  --report docs/backfill-expansion-probe-sample.md
```

2. 샘플 결과 확인

- 다운로드 파일 생성 없음
- `data/raw`, `data/md` 변화 없음
- `probe-sample.jsonl` 생성
- sample report 생성
- `api2.govpress.cloud` 호출 없음

3. 전체 정찰

```bash
python -m govpress_mcp.probe_backfill \
  --date-range 1999-02-18..2021-04-17 \
  --data-root /home/wavel/projects/govpress-mcp/data \
  --log-json data/fetch-log/probe-19990218-20210417.jsonl \
  --report docs/backfill-expansion-probe.md \
  --resume
```

## 완료 후 보고

- 총 날짜 수
- 성공 날짜 / 실패 날짜
- 총 문서 수
- 연도별 문서 수
- `hwpx` / `hwp` / `pdf` / `odt` / `no_attachment` 비중
- HWP 예상 건수
- PDF 예상 건수
- 예상 raw 증가량
- 예상 전체 소요시간
- 다음 권장 백필 구간
