# 확장 백필 2차 배치 보고서

- 작성일: 2026-04-25
- 대상 기간: `2016-04-19..2021-04-18`
- 실행 로그: `data/fetch-log/expanded-backfill-batch2-api-hwpx-hwp.jsonl`
- HWP 큐: `data/fetch-log/hwp-queue-expanded-batch2.jsonl`
- HWP 전송 manifest: `data/fetch-log/hwp-transfer-manifest-expanded-batch2.txt`

## 처리 결과

| action | 계획 | 결과 |
|---|---:|---|
| `api_text_only` | 8,615 | 8,615 MD 생성 |
| `download_hwpx` | 2 | 1 성공, 1 conversion_failed |
| `download_hwp` | 87,724 | 87,724 다운로드 및 큐 생성 |
| `download_pdf` | 2,001 | 미실행, PDF 단계에서 별도 처리 |

HWP 재시작 전 순차 다운로드에서 2,796건을 먼저 완료했고, 이후 `--concurrency 8 --resume` 병렬 다운로드로 나머지를 처리했다. 중간 실패 12건은 모두 `RemoteDisconnected`였고, 실제 네트워크 재시도로 전량 성공했다.

## HWP 큐 검증

| 항목 | 값 |
|---|---:|
| 큐 총 건수 | 87,724 |
| unique 문서ID | 87,724 |
| 중복 | 0 |
| raw 실존 | 87,724 |
| raw 누락 | 0 |
| 총 크기 | 119.64 GiB |

## 속도 비교

| 방식 | 처리 건수 | 측정 시간 | 속도 |
|---|---:|---:|---:|
| 순차 다운로드 | 2,796 | 24.64분 | 113.5건/분 |
| 병렬 다운로드 (`concurrency=8`) | 16,995 | 18.21분 | 933.2건/분 |

병렬 다운로드는 순차 대비 약 8.2배 빠르다. 후반부 5분 평균도 약 850~900건/분 수준을 유지했다.

## 전송 분할

대상 파일이 119.64 GiB이므로 월별 분할 manifest를 생성했다.

- 분할 디렉터리: `data/fetch-log/hwp-transfer-batch2-splits`
- 분할 파일 수: 52개

연도별 크기:

| 연도 | 건수 | 크기 |
|---|---:|---:|
| 2016 | 14,114 | 17.28 GiB |
| 2017 | 17,522 | 22.15 GiB |
| 2018 | 4,283 | 5.21 GiB |
| 2019 | 21,391 | 26.78 GiB |
| 2020 | 23,573 | 37.03 GiB |
| 2021 | 6,841 | 11.17 GiB |

## 다음 단계

1. 서버H로 월별 또는 연도별 HWP 전송.
2. 서버H COM 변환 실행.
3. 산출 `.hwpx` 실존 검증. `SaveAs` false success 방지는 스크립트에 반영 완료.
4. 변환된 HWPX를 서버W로 회수.
5. `hwp-queue-expanded-batch2.jsonl` 기반 M4 재처리.
