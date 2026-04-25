# 확장 백필 Manifest 계획

작성일: 2026-04-25

## 현재 기준

- 정찰 범위: `1999-02-18..2026-04-18`
- metadata 원본: `data/fetch-log/probe-items-19990218-20260418-v5.jsonl`
- SQLite 적재 DB: `data/probe-metadata.db`
- 기준 테이블: `probe_backfill_status`
- 기준 단위: `news_item_id` unique 문서ID
- 이미 수집된 문서: `129,901`
- 확장 후보:
  - `api_text_only`: `62,128`
  - `download_hwpx`: `339`
  - `download_pdf`: `5,162`
  - `download_hwp`: `237,102`
  - `skip_or_review`: `5,095`

## 목표

실제 백필 실행 전에 `probe-metadata.db`를 기준으로 manifest를 생성한다. manifest는 다운로드·변환 작업의 입력으로 사용하며, 모든 항목은 `news_item_id` 기준으로 중복 없이 생성한다.

## Manifest 산출물

| 파일 | 대상 | 설명 |
|---|---:|---|
| `data/fetch-log/manifest-api-text.jsonl` | 62,128 | 첨부 없음. API `DataContents` 본문으로 MD 생성 |
| `data/fetch-log/manifest-hwpx.jsonl` | 339 | HWPX 1개 선택 후 다운로드·변환 |
| `data/fetch-log/manifest-pdf.jsonl` | 5,162 | PDF 1개 선택 후 다운로드·변환 |
| `data/fetch-log/manifest-hwp-YYYY.jsonl` | 237,102 | HWP 1개 선택. 서버H COM 변환용 연도별 분할 |
| `data/fetch-log/manifest-review.jsonl` | 5,095 | 기타/ODT/불명확 케이스 수동 검토 |
| `docs/backfill-manifest-report.md` | - | 생성 통계와 실행 순서 |

## Manifest Row 형식

공통 필드:

```json
{
  "news_item_id": "156756430",
  "target_date": "2026-04-18",
  "approve_date": "04/18/2026 03:04:21",
  "title": "문서 제목",
  "department": "부처명",
  "original_url": "https://www.korea.kr/...",
  "selected_format": "hwpx",
  "action": "download_hwpx"
}
```

첨부 다운로드 manifest 추가 필드:

```json
{
  "attachment": {
    "file_name": "보도자료.hwpx",
    "file_url": "https://www.korea.kr/common/download.do?...",
    "extension": ".hwpx",
    "is_appendix": false
  }
}
```

API 본문 manifest 추가 필드:

```json
{
  "data_contents_html": "<p>...</p>",
  "data_contents_text": "본문",
  "data_contents_text_length": 1234
}
```

## 첨부 선택 규칙

1. `selected_format`과 확장자가 일치하는 첨부만 후보로 둔다.
2. 후보 중 `is_appendix = false`를 우선한다.
3. 같은 조건이 여러 개면 `attachment_index`가 가장 작은 것을 선택한다.
4. 후보가 없으면 `manifest-review.jsonl`로 보낸다.
5. HWPX가 있으면 HWP/PDF는 받지 않는다. HWP가 있으면 PDF는 받지 않는다.

## 실행 우선순위

1. `api_text_only`  
   다운로드와 외부 변환이 필요 없다. API 본문으로 MD를 바로 생성할 수 있어 가장 빠른 증분이다.

2. `download_hwpx`  
   수량이 `339`건으로 작고 기존 HWPX 변환 파이프라인을 재사용할 수 있다.

3. `download_pdf`  
   `5,162`건. 기존 M5 PDF 경로를 재사용하되, 먼저 100건 샘플로 실패율을 확인한다.

4. `download_hwp`  
   `237,102`건. 서버H COM 변환 병목이 크므로 연도별 manifest로 나누고, 연도 단위 또는 월 단위로 실행한다.

5. `skip_or_review`  
   ODT-only, 기타 확장자, 첨부 선택 불가 케이스를 수동 분류한다.

## 구현할 CLI

```bash
python -m govpress_mcp.build_backfill_manifest \
  --probe-db data/probe-metadata.db \
  --out-dir data/fetch-log \
  --report docs/backfill-manifest-report.md
```

옵션:

- `--action api_text_only|download_hwpx|download_pdf|download_hwp|review|all`
- `--year YYYY`
- `--sample N`
- `--overwrite`

## 완료 기준

- action별 manifest row 수가 `probe_backfill_status` 집계와 일치한다.
- `download_*` manifest의 모든 row에 선택된 `attachment.file_url`이 있다.
- HWP manifest는 연도별 파일로 분할된다.
- `docs/backfill-manifest-report.md`에 action별 건수, 연도별 HWP 건수, 누락 첨부 건수를 기록한다.
- 대용량 manifest 파일은 `data/` 아래에 두고 Git에는 포함하지 않는다.

## 다음 실행 지시

Codex에 보낼 지시:

```text
docs/backfill-manifest-plan.md 기준으로 build_backfill_manifest.py를 구현하고,
manifest를 생성한 뒤 docs/backfill-manifest-report.md를 작성해라.
실제 다운로드/변환은 아직 시작하지 마라.
```
