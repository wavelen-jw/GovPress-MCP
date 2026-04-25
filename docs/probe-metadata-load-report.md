# Probe Metadata SQLite 적재 보고서

- 생성 시각: 2026-04-25 12:24:22
- 입력: `data/fetch-log/probe-items-19990218-20260418-v5.jsonl`
- DB: `data/probe-metadata.db`
- 입력 item row: 457,609건
- unique 문서ID: 439,727건
- 중복 item row: 17,882건
- 첨부: 644,877건
- 실패 날짜: 7일

## 수집 상태 대조

| action | count |
|---|---:|
| download_hwp | 237,102 |
| already_collected | 129,901 |
| api_text_only | 62,128 |
| download_pdf | 5,162 |
| skip_or_review | 5,095 |
| download_hwpx | 339 |

## 우선 포맷

| selected_format | count |
|---|---:|
| hwp | 269,714 |
| hwpx | 96,721 |
| no_attachments | 62,128 |
| pdf | 6,069 |
| other | 5,088 |
| odt_only | 7 |
