# M1 작업 프롬프트 — bulk_ingest.py 스켈레톤 완성 + 10건 스모크

이 프롬프트는 AGENTS.md §4.1의 **마일스톤 M1만** 다룬다. M2(1개월 리허설)와 M3(5년 백필)는 별도 프롬프트(`bulk_ingest_phase1_m2.md`, `bulk_ingest_phase1_m3.md`)로 분리되어 사람 승인 후에 주입된다.

> **M2/M3를 임의로 착수하지 말 것.** M1 완료 조건이 전부 ✅ 되면 §4.1 보고 형식으로 출력하고 멈춰라.

---

## 작업 지시

`AGENTS.md`를 먼저 읽고 §1~§3의 불변 조건을 전부 준수하라. 본 프롬프트는 §4.1에 정의된 M1 완료 조건을 모두 ✅ 만들 때까지의 지시다.

### 세팅

1. `gov-md-converter`를 submodule로 추가 + editable install:
   ```bash
   git submodule add https://github.com/wavelen-jw/gov-md-converter vendor/gov-md-converter
   pip install -e vendor/gov-md-converter
   # 또는 사전 빌드 wheel:
   # pip install vendor/gov-md-converter/dist/govpress_converter-0.1.11-py3-none-any.whl
   ```
2. 크롤러 모듈을 복사한다 (**submodule 하지 말 것**):
   ```bash
   mkdir -p src/govpress_mcp/vendored
   cp /path/to/GovPress_PDF_MD/server/app/adapters/policy_briefing.py \
      src/govpress_mcp/vendored/policy_briefing.py
   ```
   복사 파일 상단에 다음 주석 삽입:
   ```python
   # Source: GovPress_PDF_MD@<git-sha> server/app/adapters/policy_briefing.py
   # Vendored on YYYY-MM-DD. Do not edit without updating the SHA marker.
   ```

### 구현

`src/govpress_mcp/bulk_ingest.py`의 TODO·스켈레톤을 채워 실제 동작하도록 만든다. 채워야 할 것:

- `src/govpress_mcp/paths.py` — `raw_path`, `md_path`, `atomic_write_bytes`, `atomic_write_text`, `ensure_dirs`
- `src/govpress_mcp/checksums.py` — SQLite 기반 `Store` 클래스 (`get`, `put`)
- `src/govpress_mcp/frontmatter.py` — `build(item, entity_type, sha256, revision, raw_path) -> dict`, `prepend(md, fm) -> str`. YAML 앞머리 블록으로 직렬화
- `src/govpress_mcp/entity_classify.py` — 최소한 중앙·광역 구분. 기초/모호는 `unknown`
- `src/govpress_mcp/ratelimit.py` — `throttle()` 코루틴 (0.3초 간격 보장), `RetryableError`, `with_retry` 데코레이터 (429/503 exponential backoff, 최대 5회)
- `FORBIDDEN_HOSTS` 차단 훅 — `urllib` monkey patch 또는 `httpx` 이벤트 훅. `api2.govpress.cloud` 접근 시 즉시 예외.

### 테스트

- `tests/test_entity_classify.py` — 샘플 10개 department 문자열로 분류 결과 확인
- `tests/test_frontmatter.py` — 필수 필드 전부 존재, YAML 파싱 round-trip
- `tests/test_idempotency.py` — 같은 sha256이면 skip이 결정론적으로 일어나는지 검증 (mock으로 `download_item_hwpx` 고정)

### 10건 E2E 스모크

```bash
python -m govpress_mcp.bulk_ingest --date 2026-04-10 --limit 10 --data-root /home/$USER/govpress-mcp/data
```

결과 확인:

```bash
ls /home/$USER/govpress-mcp/data/raw/2026/04/ | wc -l
ls /home/$USER/govpress-mcp/data/md/2026/04/ | wc -l
sqlite3 /home/$USER/govpress-mcp/data/fetch-log/checksums.db "SELECT COUNT(*) FROM checksums"
head -20 /home/$USER/govpress-mcp/data/md/2026/04/*.md | head -40
```

재실행해도 sha256 동일이면 로그에 `SKIP: already fetched, sha256=...` 만 10줄 찍혀야 한다.

---

## M1 완료 조건 (전부 ✅ 될 때까지 종료 금지)

AGENTS.md §4.1을 그대로 재인용한다.

- [ ] `vendor/gov-md-converter` submodule 등록 + editable install 성공
- [ ] `src/govpress_mcp/vendored/policy_briefing.py` 복사 + 출처 SHA 주석
- [ ] `list_items(date(2026,4,10))` 10건 end-to-end (크롤 → HWPX 저장 → sha256 → MD 저장 + frontmatter)
- [ ] 재실행 idempotency (`SKIP: already fetched, sha256=...` 로그 10줄)
- [ ] `pytest -q` 3개 통과
- [ ] 서비스키가 로그·커밋·주석·frontmatter 어디에도 없음 (전수 grep)
- [ ] `api2.govpress.cloud` 접속 로그 0건 (FORBIDDEN_HOSTS 훅 발동 로그는 있어도 OK)

---

## M1 완료 보고 형식

`docs/phase1-smoke-report.md`를 만들어 아래 형식으로 기록하고, Codex 세션 마지막에 동일 요약을 표준 출력에 찍는다.

```markdown
# M1 스모크 리포트

- 실행 날짜: YYYY-MM-DD HH:MM KST
- 테스트 대상 날짜: 2026-04-10
- 성공: N건 / 전체 M건
- skip 분포:
  - hwp_legacy: X건
  - no_primary_hwpx: Y건
  - conversion_failed: Z건
- 평균 처리 시간 (다운로드+변환): N.N 초/건
- pytest: 3/3 pass
- 서비스키 전수 grep: clean
- FORBIDDEN_HOSTS 발동 횟수: 0 (또는 N)
- 사람 확인 요청 사항: ...
```

표준 출력 마지막 줄에는 다음 한 줄만 남겨라. 스크립트로 파싱한다.

```
M1 완료. 10건 스모크 성공. 승인 대기.
```

**이후 M2 착수는 사람이 `M2 진행` 이라고 지시할 때까지 금지.**

---

## 금지 사항 재확인 (AGENTS.md §4.5 비상 호출 조건)

- `api2.govpress.cloud` HTTP 호출 ✕
- 서비스키를 코드·로그·커밋·frontmatter에 노출 ✕
- `/mnt/c/...` 경로에 데이터 저장 ✕
- `PolicyBriefingCache.warm_item()` 호출 ✕
- M2/M3 임의 착수 ✕
- 새 설계 결정 (사람에게 먼저 물어라) ✕
