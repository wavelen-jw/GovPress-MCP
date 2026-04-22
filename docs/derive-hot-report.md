# Derive Hot Report

## Summary

- mode: `incremental recovery`
- corpus md files: `130,012`
- indexed docs: `129,934`
- unindexed docs: `78`
- corpus coverage: `99.94%`
- first md: `data/md/2021/04/156445671.md`
- last md: `data/md/2026/04/156756992.md`
- last checkpoint: `data/md/2026/04/156756992.md`

## Index Totals

- qdrant points: `454,125`
- qdrant indexed_vectors_count: `452,598`
- sqlite briefing_chunks_meta rows: `454,125`
- sqlite briefing_fts rows: `454,125`
- fts5 tokenizer: `unicode61 trigram`
- average chunks per indexed doc: `3.50`

## Recovery Run

This run repaired the missing index set detected after the interrupted full build.

- processed md files: `4,085`
- total chunks: `11,108`
- failures: `78`

### Speed

- wall clock: `2,113.00s` (`35m 13s`)
- embedding time: `358.94s`
- docs/sec: `1.93`
- docs/min: `116.0`
- chunks/sec: `5.26`
- chunks/min: `315.4`
- embedding-only chunks/sec: `30.94`
- embedding-only chunks/min: `1,856.7`

## What Actually Happened

It initially looked like the index had rolled back from `2026-03` to `2023-04`, but that was not a real 3-year rollback.

The actual missing set was:

- pre-2026 scattered misses: `71`
- `2026-03`: `2,321`
- `2026-04`: `1,691`
- other 2026: `2`

So the real state was:

- a mostly completed corpus index,
- plus a small scattered backlog across older years,
- plus a large unfinished tail in `2026-03 ~ 2026-04`.

## Fixes Applied During Recovery

1. `frontmatter.parse()` now supports multiline continuation lines.
2. `derive_hot --sample` no longer overwrites the production checkpoint/report.
3. regression tests were added for both behaviors.

Relevant files:

- `src/govpress_mcp/frontmatter.py`
- `src/govpress_mcp/derive_hot.py`
- `tests/test_frontmatter.py`
- `tests/test_derive_hot.py`

## Remaining Failures

All remaining `78` failures are `HTTP 400`.

These documents are still missing from `indexed_docs` and should be tracked as a separate backlog rather than treated as a corpus-wide indexing failure.

### Failure List

- `/home/wavel/projects/govpress-mcp/data/md/2021/04/156448652.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2021/07/156460725.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2021/09/156471194.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2021/10/156474384.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2021/10/156475970.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2021/10/156476814.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2021/11/156480189.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2021/11/156482829.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2022/02/156494285.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2022/04/156501757.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2022/04/156504928.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2022/07/156518091.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2022/08/156519873.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2022/08/156521345.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2022/11/156535266.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2022/11/156537317.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2022/12/156540679.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2023/03/156557727.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2023/04/156562858.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2023/04/156565214.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2023/04/156565216.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2023/06/156572947.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2023/06/156573735.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2023/06/156576868.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2023/10/156593842.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2023/12/156607630.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/01/156613218.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/01/156613333.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/02/156614137.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/02/156615418.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/02/156616169.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/03/156619624.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/04/156623236.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/04/156625833.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/04/156625835.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/04/156626521.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/05/156629552.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/05/156629553.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/05/156632832.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/06/156634226.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/06/156634227.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/06/156638294.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/07/156641785.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/08/156645926.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/08/156646472.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/08/156647204.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/08/156647941.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/09/156649606.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/09/156651724.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/09/156651854.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/09/156652444.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/09/156653358.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/10/156653360.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/10/156654842.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/11/156659732.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/11/156662672.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/12/156665151.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2024/12/156666946.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2025/04/156735512.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2025/05/156687724.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2025/05/156688878.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2025/05/156691743.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2025/06/156712614.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2025/07/156712625.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2025/07/156712628.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2025/09/156734001.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2025/09/156734005.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2025/10/156713844.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2025/10/156720171.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2025/10/156723188.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2025/11/156725272.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2026/02/156745936.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2026/02/156746501.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2026/04/156752301.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2026/04/156752326.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2026/04/156752605.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2026/04/156753083.md`: HTTPError: HTTP Error 400: Bad Request
- `/home/wavel/projects/govpress-mcp/data/md/2026/04/156753469.md`: HTTPError: HTTP Error 400: Bad Request
