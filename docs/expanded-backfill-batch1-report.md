# 확장 백필 1차 배치 보고서

- 작성일: 2026-04-25
- 대상 기간: `2021-04-19..2026-04-18`
- 입력 기준: `data/fetch-log/manifest-*.jsonl`
- 실행 로그: `data/fetch-log/expanded-backfill-batch1*.jsonl`
- HWP 전송 큐: `data/fetch-log/hwp-queue-expanded-batch1.jsonl`

## 계획 대비 처리 현황

| action | 계획 | 처리 | 결과 |
|---|---:|---:|---|
| `api_text_only` | 865 | 865 | MD 생성 완료 |
| `download_hwpx` | 337 | 62 | raw 저장 후 변환 실패, 나머지 275건 보류 |
| `download_pdf` | 8 | 8 | raw 저장 후 변환 실패 |
| `download_hwp` | 161 | 161 | 서버H COM 변환 큐 생성 완료 |
| `skip_or_review` | 2,213 | 0 | 별도 수동 검토 대상 |

## 결과 분포

| action | status | count |
|---|---|---:|
| `api_text_only` | `success` | 865 |
| `download_hwpx` | `conversion_failed` | 62 |
| `download_pdf` | `conversion_failed` | 8 |
| `download_hwp` | `hwp_downloaded` | 108 |
| `download_hwp` | `skip_sha` | 53 |

## HWP 큐

| 항목 | 값 |
|---|---:|
| 큐 총 건수 | 161 |
| unique 문서ID | 161 |
| 중복 | 0 |
| raw 실존 | 161 |
| 누락 | 0 |
| 총 크기 | 0.20 GiB |

HWP 큐 reason 분포:

| reason | count |
|---|---:|
| `expanded_backfill_hwp` | 108 |
| `expanded_backfill_hwp_existing_raw` | 53 |

`skip_sha` 53건은 이미 동일 SHA의 raw HWP가 존재하던 항목이다. 재실행 시 큐 누락이 재발하지 않도록 `run_backfill_manifest.py`를 보강했다.

## 변환 실패

| 포맷 | 건수 | raw 실존 | raw 크기 | 비고 |
|---|---:|---:|---:|---|
| HWPX | 62 | 62 | 151.69 MiB | 일부는 HTML/error 또는 0 byte, 일부는 converter XML 파서 실패 |
| PDF | 8 | 8 | 9.81 MiB | 일부는 1 KiB 미만 응답, 나머지는 converter 실패 |

HWPX는 337건 중 62건을 먼저 처리하다가 연속 변환 실패가 확인되어 중단했다. 이번 배치의 HWPX 잔여 275건은 raw 다운로드/변환을 보류한다.

## 현재 결론

- 확장 백필 1차 배치에서 API 본문만 있는 865건은 즉시 MD로 반영됐다.
- HWP 161건은 서버H COM 변환 대기 상태다.
- HWPX/PDF 실패 항목은 raw 파일 품질과 converter 개선 범위를 분리해서 후속 분석해야 한다.
- 다음 5년 배치로 넘어가기 전, HWP COM 변환과 M4 재처리 절차를 먼저 수행하는 것이 안전하다.
