# M5 PDF Backfill Report

## Summary

- 실행 범위: `2021-04-18 ~ 2026-04-18`
- 입력 기준:
  - 기존 raw PDF 보유, MD 미생성: `915`
  - `pdf-queue.jsonl` 잔여 대상: `287`
  - 총 처리 대상: `1,202`
- 최종 결과:
  - `pdf_existing_success`: `907`
  - `pdf_downloaded_success`: `110`
  - 전체 성공 MD 생성: `1,017`
  - `conversion_failed`: `10`
  - `other_download_failed`: `175`
  - `pdf_missing`: `0`
  - `item_metadata_missing`: `0`
  - 최종 `date_failed`: `0`
- 최종 성공률: `84.61%`

## Execution

- 본 실행: `2026-04-21 16:29:37 ~ 2026-04-21 17:17:40 KST`
- 재시도 실행: `2026-04-21 17:19:38 ~ 2026-04-21 17:19:46 KST`
- 재시도 대상 일자: `4일`
  - `2021-08-26`
  - `2022-03-03`
  - `2023-07-07`
  - `2023-12-26`
- 재시도 회복:
  - 기존 raw PDF 변환 `+2`
  - 신규 PDF 다운로드+변환 `+2`
  - 미회복 `other_download_failed 2`

## Speed

- 본 실행 평균 속도: `21.08건/분` (`0.351건/초`)
- 전체 wall-clock 기준 속도: `20.28건/분` (`0.338건/초`)
- 평균 처리 시간: `0.048초/건`

## Failure Breakdown

- `conversion_failed`: `10`
- `other_download_failed`: `175`
  - `download_failed_html_error_page`: `163`
  - `download_failed_empty_payload`: `12`

## Output

- `source_format=hwpx`: `128,884`
- `source_format=hwp`: `53`
- `source_format=pdf`: `1,025`
- Markdown 파일: `129,901`

## Storage

- raw `*.hwpx`: `129,133 files / 197.04 GiB`
- raw `*.hwp`: `33,853 files / 52.60 GiB`
- raw `*.pdf`: `1,027 files / 0.71 GiB`
- raw total: `250.30 GiB`
- markdown total: `1.05 GiB`

참고:
- raw PDF 파일은 `1,027`개지만, 이 중 `2`개는 `conversion_failed` orphan raw 파일이다.
- retained corpus 기준 PDF는 `1,025`건이다.

## Artifacts

- 실행 로그: `data/fetch-log/m5-reprocess.jsonl`
- 재시도 로그: `data/fetch-log/m5-retry-4dates.jsonl`
- 현재 PDF 큐: `data/fetch-log/pdf-queue.jsonl`
- historical PDF 큐 백업: `data/fetch-log/pdf-queue.original-20260419-214848.jsonl`
