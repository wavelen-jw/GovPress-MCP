# M4 HWP Reprocess Report

## Summary

- 실행 범위: `2021-04-18 ~ 2026-04-18`
- 입력 큐: `33,853` 문서ID (`hwp-queue.jsonl`)
- 최종 결과:
  - `success`: `33,800`
  - `hwp_distribution_only`: `52`
  - `conversion_failed`: `1`
  - `item_metadata_missing`: `0`
  - 최종 `date_failed`: `0`
- 최종 성공률: `99.84%`

## Execution

- 본 실행: `2026-04-21 14:55:18 ~ 2026-04-21 16:03:46 KST`
- 재시도 실행: `2026-04-21 16:08:54 ~ 2026-04-21 16:09:01 KST`
- 본 실행 처리 일수: `1,635일`
- 재시도 일수: `4일`
- 재시도 회복: `25건`
  - `2025-02-10`: `4건`
  - `2025-06-09`: `6건`
  - `2025-10-15`: `13건`
  - `2025-11-02`: `2건`
- 재시도 전 실패 원인: 일자별 `HTTP 502 Bad Gateway`

## Speed

- 본 실행 평균 속도: `493.2건/분`
- 본 실행 평균 속도: `8.22건/초`
- 전체 wall-clock 기준 속도: `458.5건/분`
- 평균 처리 시간: `0.048초/건`

## Output

- `source_format=hwpx`: `128,884`
- `source_format=hwp`: `53`
- `source_format=pdf`: `915`
- Markdown 파일: `128,884`

## Storage

- raw `*.hwpx`: `129,133` files / `197.04 GiB`
- raw `*.hwp`: `33,853` files / `52.60 GiB`
- raw `*.pdf`: `915` files / `0.66 GiB`
- raw total: `250.30 GiB`
- markdown total: `1.02 GiB`

## Remaining Issues

- `hwp_distribution_only`: `52`
  - 한/글 배포 제한 문서로 판정되어 영구 skip
  - 목록: `data/fetch-log/hwpx-missing-52.txt`
- `conversion_failed`: `1`
  - `news_item_id=156468376`
  - converter 개선 후 별도 재시도 대상

## Artifacts

- 실행 로그: `data/fetch-log/m4-reprocess.jsonl`
- 재시도 로그: `data/fetch-log/m4-retry-4dates.jsonl`
- 배포제한 목록: `data/fetch-log/hwpx-missing-52.txt`
