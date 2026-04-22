# Phase 1 Final Report

범위: `2021-04-18 ~ 2026-04-18`

Phase 1은 정책브리핑 원문을 수집해 Markdown corpus를 만드는 단계였다. 이 문서는 M3~M5의 공개용 최종 결과만 요약한다.

## Final Corpus

Final retained corpus at `data/`:

| Category | Count |
|---|---:|
| Markdown files | `129,901` |
| `source_format=hwpx` | `128,884` |
| `source_format=hwp` | `53` |
| `source_format=pdf` | `1,025` |

Final raw file snapshot:

| Raw format | Files | Size |
|---|---:|---:|
| `*.hwpx` | `129,133` | `197.04 GiB` |
| `*.hwp` | `33,853` | `52.60 GiB` |
| `*.pdf` | `1,027` | `0.71 GiB` |
| Raw total | — | `250.30 GiB` |
| Markdown total | `129,901` | `1.05 GiB` |

Notes:

- raw `*.pdf` is physically `1,027` files, but retained PDF corpus is `1,025`; `2` files are orphan raw PDFs tied to `conversion_failed`.
- raw `*.hwpx` is physically `129,133` files, while retained `source_format=hwpx` documents are `128,884`; the remainder includes unresolved conversion failures.

Yearly Markdown counts:

| Year | Markdown files |
|---|---:|
| `2021` | `19,271` |
| `2022` | `23,951` |
| `2023` | `27,219` |
| `2024` | `27,529` |
| `2025` | `23,993` |
| `2026` | `7,938` |

## Milestone Summary

### M3 — HWPX Backfill

- Backfill target range completed: `2021-04-18 ~ 2026-04-18`
- HWPX conversion success during base backfill: `91,086`
- HWP queue constructed: `33,853`
- PDF fallback queue identified and later normalized for M5
- M3 retained-corpus 최종 분포:
  - `stored_hwpx`: `95,084`
  - `stored_hwp`: `33,853`
  - `stored_pdf`: `915`
  - `no_attachments`: `3,076`
  - `odt_only`: `2`
  - unresolved failed: `367`

### M3.5 — HWP Transfer Preparation

- `hwp-queue.jsonl` verified: `33,853 / 33,853` HWP files physically present
- Transfer manifest generated: `data/fetch-log/hwp-transfer-manifest.txt`
- HWP transfer size for server H COM conversion: `52.60 GiB`

### M4 — HWP Reprocess

- Input queue: `33,853`
- Success: `33,800`
- `hwp_distribution_only`: `52`
- `conversion_failed`: `1`
- Final `date_failed`: `0`
- Success rate: `99.84%`

### M5 — PDF Backfill

- Total processed: `1,202`
  - existing raw PDF without MD: `915`
  - queue-only PDF fallback targets: `287`
- Success:
  - `pdf_existing_success`: `907`
  - `pdf_downloaded_success`: `110`
  - total: `1,017`
- Failure:
  - `conversion_failed`: `10`
- `other_download_failed`: `175`
    - `download_failed_html_error_page`: `163`
    - `download_failed_empty_payload`: `12`
- Final `date_failed`: `0`
- Success rate: `84.61%`

## Queue Snapshot

Current queue/log files:

| File | Rows | Meaning |
|---|---:|---|
| `data/fetch-log/hwp-queue.jsonl` | `33,853` | Canonical HWP COM input log |
| `data/fetch-log/pdf-queue.jsonl` | `287` | Canonical remaining PDF fallback queue after normalization |
| `data/fetch-log/pdf-queue.original-20260419-214848.jsonl` | `43,754` | Historical append-only PDF queue backup |
| `data/fetch-log/failed.jsonl` | `988` | Historical failure log across phases and retries |

Interpretation:

- `hwp-queue.jsonl` is canonical and one-row-per-document.
- `pdf-queue.jsonl` is no longer a historical append log; it was normalized to the actual remaining M5 PDF fallback set before M5 execution.
- The old append-only PDF queue was preserved as `pdf-queue.original-20260419-214848.jsonl`.

## Speed Summary

### M4

- Main-run throughput: `493.2건/분` (`8.22건/초`)
- Whole-run wall-clock throughput: `458.5건/분`
- Mean processing time: `0.048초/건`

### M5

- Main-run throughput: `21.08건/분` (`0.351건/초`)
- Whole-run wall-clock throughput: `20.28건/분` (`0.338건/초`)
- Mean processing time: `0.048초/건`

Interpretation:

- M4 was CPU-local reprocessing against already uploaded `.hwpx` files and therefore much faster.
- M5 remained network- and converter-dependent because it had to reuse or download raw PDFs and run `convert_pdf()`.

## Remaining Issues

Retained unresolved items after Phase 1:

- M4:
  - `hwp_distribution_only`: `52`
  - `conversion_failed`: `1`
- M5:
  - `conversion_failed`: `10`
  - `download_failed_html_error_page`: `163`
  - `download_failed_empty_payload`: `12`

Operational interpretation:

- `hwp_distribution_only` items are permanently skipped due to Hangul distribution restriction.
- `conversion_failed` items are candidates for future converter improvement and targeted reprocessing.
- `download_failed_*` items are upstream attachment-response problems rather than successful raw corpus additions.

## Artifact Index

- Data notice: [`../LICENSE-data`](../LICENSE-data)
- HWP transfer manifest: `data/fetch-log/hwp-transfer-manifest.txt`
- HWP distribution-only list: `data/fetch-log/hwpx-missing-52.txt`
- M4 logs:
  - `data/fetch-log/m4-reprocess.jsonl`
  - `data/fetch-log/m4-retry-4dates.jsonl`
- M5 logs:
  - `data/fetch-log/m5-reprocess.jsonl`
  - `data/fetch-log/m5-retry-4dates.jsonl`
