# Phase 1 Backfill Report

Document-ID-based final retained-corpus statistics are maintained separately in [`m3-final-stats.md`](m3-final-stats.md).

Phase 1 backfill is complete for the target range `2021-04-18 ~ 2026-04-18`, including the follow-up single-pass attachment reconciliation with priority `hwpx > hwp > pdf`.

## Summary

- Execution window: `2026-04-18 19:31 KST` to `2026-04-19 13:44 KST`
- Covered target range: `2021-04-18 ~ 2026-04-18`
- Total processed item rows: `174,351`
- Successful HWPX conversions: `91,086` (`52.24%` of processed rows)
- Generated Markdown files: `93,353`
- Frontmatter v2 check: `extracted_by:` `0`건
- Forbidden host hits: `0`

## Single-Pass Reconciliation

- Execution window: `2026-04-19 14:54 KST` to `2026-04-19 20:44 KST`
- Retry window: `2026-04-19 20:56 KST` to `2026-04-19 20:58 KST`
- Priority: `hwpx > hwp > pdf`
- Unified run item rows: `144,038`
- Retry run item rows: `1,138`
- Final reconciliation item rows: `145,176`
- Final source-format totals:
  - `hwpx`: `95,084`
  - `hwp`: `33,853`
  - `pdf`: `915`
- Final queues:
  - `hwp-queue.jsonl`: `33,853`
  - final raw `.pdf`: `915`
- Retry result: `11/11` failed dates recovered, final `date_failed=0`

## Output Snapshot

- Raw corpus size: `199.84 GiB`
- Markdown corpus size: `0.72 GiB`
- Raw layout: `data/raw/{yyyy}/{mm}/{news_item_id}.hwpx`
- Markdown layout: `data/md/{yyyy}/{mm}/{news_item_id}.md`

Additional raw layouts produced by the reconciliation pass:

- `data/raw/{yyyy}/{mm}/{news_item_id}.hwp`
- `data/raw/{yyyy}/{mm}/{news_item_id}.pdf`

Yearly Markdown file counts:

| Year | MD files |
|---|---:|
| 2021 | 252 |
| 2022 | 15,929 |
| 2023 | 24,471 |
| 2024 | 24,972 |
| 2025 | 21,032 |
| 2026 | 6,697 |

## Skip Distribution

Base denominator: `174,351` processed rows in `data/fetch-log/backfill.jsonl`.

| Status | Count | Ratio |
|---|---:|---:|
| `success` | 91,086 | 52.24% |
| `skip_sha` | 10,149 | 5.82% |
| `pdf_queue_no_primary_hwpx` | 42,452 | 24.35% |
| `pdf_queue_hwpx_html_error_page` | 171 | 0.10% |
| `pdf_queue_hwpx_empty_payload` | 7 | 0.00% |
| `no_attachments` | 26,638 | 15.28% |
| `odt_only` | 2,392 | 1.37% |
| `hwp_legacy` | 1,191 | 0.68% |
| `conversion_failed` | 252 | 0.14% |
| `hwpx_empty_payload` (no PDF fallback) | 9 | 0.01% |
| `hwpx_html_error_page` (no PDF fallback) | 4 | 0.00% |

Notes:

- `skip_sha` means the raw HWPX payload was unchanged from a previously stored item.
- `pdf_queue_*` means the HWPX track was skipped and a PDF fallback candidate was recorded for M4.
- `hwpx_*` without `pdf_queue_` means the HWPX payload was abnormal and no primary PDF fallback was available.

## PDF Collection Summary

- Final raw PDF files: `915`
- Of these, `892` were collected by the unified single-pass reconciliation and `23` were already present beforehand
- Collection rule: only when both HWPX and HWP were unavailable

The queue file is the M4 input pool. It is larger than the M3-run-only subset because it includes earlier rehearsal and restart history already appended to the same JSONL.

## Failure Queue

- Failure file: `data/fetch-log/failed.jsonl`
- Total rows: `633`

| Failure class | Count |
|---|---:|
| `conversion_failed` | `512` |
| `download_failed` | `121` |

## Reconciliation Distribution

Base denominator: `145,176` processed rows in `data/fetch-log/unified-collect.jsonl` plus `data/fetch-log/unified-retry.jsonl`.

| Status | Count |
|---|---:|
| `skip_sha` | `103,950` |
| `hwp_attachment` | `31,720` |
| `hwp_legacy` | `1,197` |
| `pdf_collected` | `892` |
| `no_attachments` | `3,288` |
| `odt_only` | `2` |
| `conversion_failed` | `248` |
| `pdf_queue_hwpx_html_error_page` | `176` |
| `pdf_queue_hwpx_empty_payload` | `7` |
| `hwpx_html_error_page` | `4` |
| `hwpx_empty_payload` | `8` |
| `other_download_failed` | `115` |
| `success` | `1,731` |

## Performance

- Median successful conversion time: `0.266s/item`
- Mean successful conversion time: `0.313s/item`
- Mean processed throughput across the logged run window: `9,569.4 items/hour`
- Mean successful conversion throughput across the logged run window: `4,999.3 items/hour`

Recent end-of-run heartbeat sample:

- `2026-04-19 13:43:52 KST`
- Current date pointer: `2026-04-16`
- Rate: `182.9/min`
- `success=14,364`, `pdf_queue=1,611`, `no_attachments=1,145`, `skip_sha=3,065`

## Final Resume Run

The last uninterrupted resume run covered `2025-07-18..2026-04-18`.

Final `done` line from `logs/backfill.stdout`:

```text
done successful=14479 skip_sha=3069 pdf_queue=1622 no_primary_hwpx=1598 hwp_legacy=597 conversion_failed=42 forbidden_host_hits=0
```

Last two day summaries:

| Date | successful | skip_sha | pdf_queue | hwp_legacy | conversion_failed |
|---|---:|---:|---:|---:|---:|
| `2026-04-17` | 111 | 4 | 11 | 2 | 0 |
| `2026-04-18` | 4 | 0 | 0 | 0 | 0 |

## M3 Close-Out Status

The HWPX backfill itself is complete. The remaining close-out items for a strict AGENTS M3 sign-off are operational/reporting items outside the completed backfill run:

| Item | Status | Note |
|---|---|---|
| Official institution diff table | Pending | Official reference table is not yet materialized in-repo, so the `기관별 MD 개수 vs korea.kr 공식 목록` diff table is not included here yet. |
| `systemd` daily timer registration | Pending | Timer unit activation and 7-day validation were not completed in this repository state. |
| `LICENSE-data` file | Done | Added at repo root. |

## Post-M3 Final State

- Existing HWPX corpus was reused in-place via checksum lookup before download.
- Follow-up reconciliation added:
  - raw `.hwp`: `33,853` files / `52.60 GiB`
  - raw `.pdf`: `915` files / `0.66 GiB`
- Final retry-only additions:
  - `hwp +304`
  - `pdf +7`

## Final Totals

This is the final retained corpus after the M3 HWPX backfill, the single-pass attachment reconciliation, and the retry pass.

| Category | Total |
|---|---:|
| Raw `hwpx` files | `95,084` |
| Raw `hwp` files | `33,853` |
| Raw `pdf` files | `915` |
| Markdown files | `93,353` |
| `hwp-queue.jsonl` rows | `33,853` |
| `pdf-queue.jsonl` rows | `43,748` |
| `failed.jsonl` rows | `633` |

Final reconciliation distribution (`unified-collect.jsonl` + `unified-retry.jsonl`):

| Status | Count |
|---|---:|
| `skip_sha` | `103,950` |
| `hwp_attachment` | `31,720` |
| `hwp_legacy` | `1,197` |
| `pdf_collected` | `892` |
| `success` | `1,731` |
| `conversion_failed` | `248` |
| `no_attachments` | `3,288` |
| `odt_only` | `2` |
| `pdf_queue_hwpx_html_error_page` | `176` |
| `pdf_queue_hwpx_empty_payload` | `7` |
| `hwpx_html_error_page` | `4` |
| `hwpx_empty_payload` | `8` |
| `other_download_failed` | `115` |

## References

- Data notice: [`../LICENSE-data`](../LICENSE-data)
- Backfill log path: `logs/backfill.stdout`
- Item log path: `data/fetch-log/backfill.jsonl`
- PDF queue path: `data/fetch-log/pdf-queue.jsonl` (historical queue log; final raw PDF corpus is `915`)
- Failure queue path: `data/fetch-log/failed.jsonl`
- Heartbeat path: `data/fetch-log/heartbeat.jsonl`
