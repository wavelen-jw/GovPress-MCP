# M3 Final Statistics

This document records the final Phase 1 / M3 corpus state on a document-ID basis.

- Range: `2021-04-18 ~ 2026-04-18`
- Data root: `/home/wavel/projects/govpress-mcp/data`
- Counting rule: one `news_item_id` counts once in its final bucket
- Snapshot date: `2026-04-19`

## Final Classification

Final classified document IDs: `133,297`

| Final bucket | Document IDs | Ratio |
|---|---:|---:|
| Stored `hwpx` | `95,084` | `71.33%` |
| Stored `hwp` | `33,853` | `25.40%` |
| Stored `pdf` | `915` | `0.69%` |
| `no_attachments` | `3,076` | `2.31%` |
| `odt_only` | `2` | `0.00%` |
| Unresolved failed | `367` | `0.28%` |

Interpretation:

- `stored_hwpx`: final converted corpus and retained HWPX raw files
- `stored_hwp`: legacy HWP or no-primary-HWPX cases where an actual `.hwp` attachment existed
- `stored_pdf`: only collected when both HWPX and HWP were unavailable
- `no_attachments` / `odt_only`: terminal skip states
- `unresolved failed`: items still present only in `failed.jsonl`

## Stored Files And Sizes

| Category | Files | Bytes | Size |
|---|---:|---:|---:|
| Raw `hwpx` linked to retained corpus | `95,084` | `156,325,958,072` | `145.59 GiB` |
| Raw `hwp` | `33,853` | `56,476,937,875` | `52.60 GiB` |
| Raw `pdf` | `915` | `711,384,190` | `0.66 GiB` |
| Markdown | `95,084` | `770,305,673` | `0.72 GiB` |

Additional note:

- Raw `*.hwpx` files physically present: `95,332`
- Of these, `248` files / `1,064,852,205` bytes (`0.99 GiB`) are orphan raw HWPX files tied to unresolved `conversion_failed` items and are not part of the retained Markdown corpus.

## Failure Summary

`failed.jsonl` is analyzed by unique `news_item_id`, not by raw line count.

- `failed.jsonl` rows: `729`
- Unique failed document IDs: `367`
- Resolved later and retained: `0`
- Still unresolved: `367`

### Failure Classes

| Failure class | Document IDs | Ratio within failed |
|---|---:|---:|
| `conversion_failed` | `248` | `67.57%` |
| `download_failed_html_error_page` | `102` | `27.79%` |
| `download_failed_empty_payload` | `13` | `3.54%` |
| `download_failed_other` | `4` | `1.09%` |

### Top Failure Reasons

| Reason | Document IDs |
|---|---:|
| `conversion_failed: ... invalid token line 1, column 0` | `152` |
| `download_failed: ... HTML 에러 페이지` | `102` |
| `conversion_failed: ... invalid token line 1, column 1` | `46` |
| `conversion_failed: ... syntax error line 1, column 0` | `16` |
| `conversion_failed: ... invalid token line 1, column 2` | `15` |
| `download_failed: ... 비어 있습니다` | `13` |

### Failure File Sizes

| Failure bucket | Raw files | Bytes | Size |
|---|---:|---:|---:|
| `conversion_failed` orphan `hwpx` | `248` | `1,064,852,205` | `0.99 GiB` |
| `download_failed_*` retained raw files | `0` | `0` | `0 GiB` |

Interpretation:

- `conversion_failed` already has downloaded raw HWPX files, but Markdown generation failed.
- `download_failed_*` never produced a retained raw source file.

## `skip_sha` Analysis

`skip_sha` is an execution-path event, not a final corpus bucket. It means the selected source matched a previously stored raw payload and was skipped before writing a new file.

- Unique `skip_sha` document IDs: `100,839`

Breakdown by the final stored format of those same document IDs:

| Final stored format behind `skip_sha` | Document IDs | Ratio within `skip_sha` |
|---|---:|---:|
| `hwpx` | `93,357` | `92.58%` |
| `hwp` | `7,329` | `7.27%` |
| `pdf` | `153` | `0.15%` |

Interpretation:

- Most `skip_sha` events are reused HWPX documents from the earlier backfill.
- A smaller share corresponds to already collected HWP files.
- A very small tail corresponds to already collected PDF files.

## Queue Files

Queue files are historical append-only logs and should not be interpreted as final corpus counts without deduplicating by `news_item_id`.

| Queue file | Rows | Unique document IDs | Duplicate rows |
|---|---:|---:|---:|
| `hwp-queue.jsonl` | `33,853` | `33,853` | `0` |
| `pdf-queue.jsonl` | `43,748` | `20,830` | `22,918` |

Interpretation:

- `hwp-queue.jsonl` is already one-row-per-document.
- `pdf-queue.jsonl` contains substantial historical duplication from rehearsal, restart, and retry paths.

## Operational Status Counts

These are unique-document status counts observed across:

- `data/fetch-log/unified-collect.jsonl`
- `data/fetch-log/unified-retry.jsonl`
- `data/fetch-log/nonconversion-retry.jsonl`

| Status | Unique document IDs |
|---|---:|
| `skip_sha` | `100,839` |
| `hwp_attachment` | `31,720` |
| `hwp_legacy` | `1,197` |
| `pdf_collected` | `892` |
| `success` | `1,731` |
| `conversion_failed` | `248` |
| `no_attachments` | `3,076` |
| `odt_only` | `2` |
| `pdf_queue_hwpx_html_error_page` | `173` |
| `pdf_queue_hwpx_empty_payload` | `5` |
| `hwpx_html_error_page` | `4` |
| `hwpx_empty_payload` | `8` |
| `other_download_failed` | `115` |

## Notes

- The aborted non-conversion retry did not improve the retained corpus. The original non-conversion failed set remained unresolved on a document-ID basis.
- Converter-related failures are intentionally left for a future converter-improvement pass.
