# Govpress MCP — Codex 작업 지시서 (AGENTS.md)

이 파일은 Codex CLI가 **매 세션 시작 시 반드시 읽어야** 한다. 아래 결정은 이미 사람(준우)과 조율이 끝난 고정 사양이다. 재협상하지 말고 구현만 해라. 새 결정이 필요하면 **먼저 질문**.

---

## 0. 프로젝트 한 줄 요약

한국 정부 5년치 보도자료(중앙·광역·기초)를 Govpress 코드로 크롤·HWPX→MD 변환한 뒤, 자체 디렉토리에 저장하고 Qdrant·FTS5·SQLite로 색인해서 MCP 8개 도구로 Claude에 제공한다. 현재 단계는 **Phase A — 크롤·변환·저장 파이프라인**.

---

## 1. 불변 조건 (변경 금지)

변경이 필요해 보이면 **사람에게 먼저 물어라**. 이유 없이 재협상하면 안 된다.

### 1.1 인프라

- 실행 환경: **WSL Ubuntu 24.04** (Windows 호스트 서버W). Docker Desktop 있음.
- 작업 디렉토리 루트: `/home/wavel/projects/govpress-mcp/`. **절대 `/mnt/c/...` 금지** — Windows 드라이브 I/O 성능 문제.
- 데이터 디렉토리: `/home/wavel/projects/govpress-mcp/data/{raw,md,fetch-log}`
- Python ≥ 3.10 (변환 엔진 요구사항)
- PDF 변환이 필요한 경우에만 Java 11+ (Phase A는 HWPX만 다루므로 불필요)

### 1.2 원본 포맷 및 변환 우선순위 (2026-04-18 확정)

**변환 우선순위: HWPX 원본 > HWP → HWPX 변환 > PDF**

HWP(구버전)는 `govpress-converter`로 직접 변환 불가하지만, 한/글 COM 자동화로 HWPX로
변환하면 품질 손실 없이 처리 가능하다. PDF보다 변환 품질이 높으므로 PDF 이전 단계에서 처리한다.

**단일 패스 선택 규칙 (2026-04-19 확정):**

각 item의 첨부 메타를 한 번만 훑어 최우선 포맷 1개를 선택, 다운로드도 1회만 한다.

```python
def select_best_attachment(item) -> (format, attachment, reason):
    # 1순위: primary_hwpx 정상 (is_zip_container=True, HTML 오류 페이지·0 byte 아님)
    # 2순위: .hwp 첨부 존재 (primary_hwpx 없거나 비정상일 때 item.attachments 순회)
    # 3순위: primary_pdf 존재
    # 없음: no_attachments / odt_only
```

선택 결과별 처리:

1. **HWPX 선택** → `data/raw/{yyyy}/{mm}/{id}.hwpx` 저장 → `convert_hwpx()` → MD 생성 (`source_format: hwpx`)
2. **HWP 선택** (`hwp_legacy` 또는 `no_primary_hwpx_hwp_attachment`) → `data/raw/{yyyy}/{mm}/{id}.hwp` 저장 → `hwp-queue.jsonl` 큐잉. MD 생성 없음. M3.5(서버H COM) + M4(재처리)에서 처리.
   ```json
   {"news_item_id": "...", "approve_date": "YYYY-MM-DD", "reason": "hwp_legacy" | "no_primary_hwpx_hwp_attachment", "hwp_path": "data/raw/yyyy/mm/ID.hwp"}
   ```
3. **PDF 선택** → `pdf-queue.jsonl` 큐잉. M5에서 처리. (HWPX/HWP 둘 다 없는 경우만 도달)
   ```json
   {"news_item_id": "...", "approve_date": "YYYY-MM-DD", "reason": "no_hwpx_no_hwp"}
   ```
4. **없음** → `no_attachments` / `odt_only` 사유로 skip + 로그 한 줄.

**비정상 HWPX 판정 (HWP 2순위로 강등):**
- `본문[:15].lstrip().startswith(b"<!DOCTYPE")` 또는 `b"<html"` → `hwpx_html_error_page` → HWP 2순위로 재선택
- `len(본문) == 0` → `hwpx_empty_payload` → HWP 2순위로 재선택

**구현 주의:** `no_primary_hwpx_hwp_attachment` 건의 HWP 다운로드는 `client.download_item_hwpx()`가 아닌 `item.attachments`를 직접 순회해서 `.hwp` 확장자 첨부를 선택·다운로드해야 한다.

**각 마일스톤 담당 범위:**
| 단계 | 처리 포맷 | 실행 환경 |
|---|---|---|
| M3 | HWPX 수집·변환 (완료) | 서버W WSL |
| M3.5 단일 패스 | HWPX(skip) / HWP 수집·큐잉 / PDF 큐잉 — 5년 재스캔 | 서버W WSL |
| M3.5 COM 변환 | HWP → HWPX | **서버H Windows** (한/글 COM) |
| M4 | 변환된 HWPX 재처리 (hwp-queue 전량 소진) | 서버W WSL |
| M5 | PDF 백필 (HWPX/HWP 모두 없는 잔여분만) | 서버W WSL |

### 1.3 Govpress 웹서비스 호출 금지

- **`api2.govpress.cloud` 엔드포인트에 HTTP 호출을 절대 보내지 말 것.** 이 웹서비스는 소량 on-demand용이고, bulk 호출 시 자기 자신에 부하가 돌아온다.
- 크롤러는 `apis.data.go.kr`(korea.kr 정책브리핑 API)만 직접 호출.

### 1.4 재사용 방식 (확정)

| 대상 | 방식 | 경로 |
|---|---|---|
| `gov-md-converter` (변환 엔진, 패키지 `govpress-converter`) | **git submodule + `pip install -e`** | `vendor/gov-md-converter` |
| `GovPress_PDF_MD/server/app/adapters/policy_briefing.py` (크롤러, 비패키지 단일 모듈) | **파일 복사 (vendoring)** + 출처 커밋 SHA 주석 | `src/govpress_mcp/vendored/policy_briefing.py` |

크롤러를 submodule로 편입하지 말 것. 의존 트리가 서버 전체로 번진다.

### 1.5 API 범위

- 정책브리핑 API가 돌려주는 **전체** (중앙부처 + 광역 + 기초지자체). 화이트리스트 없음.
- 계층 구분은 frontmatter의 `entity_type` 필드(`central` / `metro` / `local`)로 표현.

### 1.6 저장 경로 규약

```
/home/wavel/projects/govpress-mcp/data/
├── raw/{yyyy}/{mm}/{news_item_id}.hwpx      # 원본 HWPX (M3) 또는 COM 변환 결과 (M3.5)
├── raw/{yyyy}/{mm}/{news_item_id}.hwp       # HWP 구버전 원본 (M3 수집, M3.5 변환 전까지 보존)
├── raw/{yyyy}/{mm}/{news_item_id}.pdf       # 원본 PDF (M5, 동일 경로 구조)
├── md/{yyyy}/{mm}/{news_item_id}.md         # 변환 결과 + frontmatter (HWPX·PDF 공용)
└── fetch-log/
    ├── checksums.db                          # SQLite: news_item_id → sha256, fetched_at, govpress_version, govpress_commit, source_format
    ├── failed.jsonl                          # 변환 실패 재시도 큐 (HWPX 트랙)
    ├── hwp-queue.jsonl                       # HWP 변환 대기 큐 (M3.5 입력 — 서버H COM 변환용)
    └── pdf-queue.jsonl                       # PDF 변환 대기 큐 (M5 입력)
```

`.hwp` 원본은 M3.5 이후에도 삭제하지 않는다. `.hwpx`와 공존 허용 (재변환 대비).

`yyyy`/`mm`는 `approve_date` 기준.

### 1.7 Frontmatter 필수 필드 (v2, 2026-04-18)

```yaml
---
id: <news_item_id>
title: <item.title>
department: <item.department>
approve_date: <ISO 8601>
entity_type: central | metro | local
original_url: <item.original_url>
sha256: <원본 파일의 sha256 — HWPX 또는 PDF>
revision: 1
govpress_version: <govpress-converter 버전, 예: 0.1.11>
govpress_commit: <gov-md-converter git SHA (editable install 기준)>
source_format: hwpx                          # hwpx | pdf
raw_path: data/raw/yyyy/mm/{news_item_id}.hwpx   # 확장자는 source_format과 일치
---
```

**v1 → v2 변경 사항**: `extracted_by: "version+sha"` 컴포짓 필드를 `govpress_version` + `govpress_commit` 두 필드로 분리, `source_format` 신규 추가. M1·M2에서 생성된 기존 MD는 `stamp_version.py`로 일괄 백필한다(stamp-patch 참조). 새로 생성하는 모든 MD는 v2 형식만 사용한다.

### 1.8 보안

- korea.kr 서비스키는 **환경변수** `GOVPRESS_POLICY_BRIEFING_SERVICE_KEY`에서만 읽는다.
- 로그·에러 메시지·커밋 메시지·frontmatter 어디에도 키를 찍지 말 것.
- `.env.example`에 **키 이름만** 남기고 값은 비워라.

### 1.9 Rate Limit (재협상 금지)

- 동시성: 최대 5 (`asyncio.Semaphore(5)` 또는 `concurrent.futures.ThreadPoolExecutor(max_workers=5)`)
- 요청 간 최소 sleep 0.3초
- HTTP 429/503 수신: exponential backoff (1s, 2s, 4s, 8s, …) 최대 5회, 이후 실패 큐로
- User-Agent: `govpress-mcp-bulk/1.0 (+https://mcp.govpress.cloud)`

---

## 2. 실제 API 시그니처 (2026-04-17 레포 실측)

### 2.1 변환 엔진 — `govpress_converter`

설치: `pip install -e vendor/gov-md-converter` (또는 `pip install vendor/gov-md-converter/dist/govpress_converter-0.1.11-py3-none-any.whl`)

```python
import govpress_converter

md_text: str = govpress_converter.convert_hwpx(
    path,                    # str | Path
    table_mode="text",       # "text" | "html"
)

md_from_pdf: str = govpress_converter.convert_pdf(
    path,                    # str | Path
    timeout=300,             # Java 11+ 필요
)
```

공개 PyPI wheel은 인터페이스 컨트랙트만 (RuntimeError를 던진다). **반드시 editable install 또는 private wheel**을 쓸 것.

### 2.2 크롤러 — `PolicyBriefingClient`

출처: `GovPress_PDF_MD/server/app/adapters/policy_briefing.py`. `src/govpress_mcp/vendored/policy_briefing.py`로 복사한 뒤 import.

```python
from govpress_mcp.vendored.policy_briefing import (
    PolicyBriefingClient,
    PolicyBriefingItem,
    PolicyBriefingAttachment,
    DownloadedPolicyBriefingFile,
)

client = PolicyBriefingClient(
    service_key=os.environ["GOVPRESS_POLICY_BRIEFING_SERVICE_KEY"],
    timeout_seconds=8,
)

# 단일 날짜만 받음. 5년 백필은 날짜 루프로 돌려라.
items: list[PolicyBriefingItem] = client.list_items(target_date)  # target_date: datetime.date

for item in items:
    if item.primary_hwpx is None:
        continue  # HWPX가 없으면 스킵
    downloaded: DownloadedPolicyBriefingFile = client.download_item_hwpx(item)
    if not downloaded.is_zip_container:
        # .hwpx 확장자인데 실제로는 HWP 바이너리 → 스킵 + 로그
        continue
    raw_bytes: bytes = downloaded.content
```

`PolicyBriefingItem` 주요 필드: `news_item_id`, `title`, `department`, `approve_date` (`"MM/DD/YYYY HH:MM:SS"` 형식), `original_url`, `attachments`, `primary_hwpx`, `primary_pdf`.

**주의**: `PolicyBriefingCache.warm_item`은 Govpress 저장 레이아웃에 묶여 있으므로 **사용하지 말 것**. `list_items` + `download_item_hwpx`까지만 재사용.

### 2.3 entity_type 판정

korea.kr API 응답에는 entity_type 필드가 없다. `department` 문자열로 룰 기반 판정:

- 중앙: `과학기술정보통신부`, `기획재정부`, `행정안전부` 등 부·처·청·위원회 이름
- 광역: `서울특별시`, `경기도`, `부산광역시` 등 "시/도"
- 기초: 시·군·구 (예: `수원시`, `강남구`)

정확한 리스트는 `행정안전부`의 지자체 코드 기준으로 따로 테이블을 만들어라. Phase 1에서는 중앙·광역만 우선 태깅하고 나머지는 `unknown`으로 두었다가 Phase B에서 확장.

---

## 3. 파일 배치

Codex가 만들 최종 구조 (Phase A 기준):

```
govpress-mcp/                             # Govpress MCP 프로젝트 루트
├── AGENTS.md                             # 이 파일
├── README.md
├── pyproject.toml
├── docker-compose.yml                    # Phase 2: Qdrant + TEI + Redis + MCP 서버
├── Dockerfile                            # Phase 2: MCP 서버 이미지
├── .env.example                          # GOVPRESS_POLICY_BRIEFING_SERVICE_KEY=
├── .gitignore                            # .env, data/, __pycache__/, vendor/gov-md-converter/.venv
├── vendor/
│   └── gov-md-converter/                 # submodule
├── src/
│   └── govpress_mcp/
│       ├── __init__.py
│       ├── vendored/
│       │   ├── __init__.py
│       │   └── policy_briefing.py        # 복사본 (출처 SHA 주석)
│       ├── bulk_ingest.py                # 크롤·변환·저장 메인 루프 (Phase 1)
│       ├── reconvert.py                  # Phase 2: conversion_failed 재처리
│       ├── derive_hot.py                 # Phase 2: MD → Qdrant + FTS5 색인
│       ├── mcp_server.py                 # Phase 2: MCP 8개 도구 FastAPI 서버
│       ├── entity_classify.py            # department → entity_type
│       ├── frontmatter.py                # 생성·파싱
│       ├── paths.py                      # 저장 경로 규약
│       ├── ratelimit.py                  # 동시성·backoff
│       └── checksums.py                  # sha256 비교, SQLite 추적
├── scripts/
│   ├── run_bulk_ingest.sh                # env 로드 + python -m govpress_mcp.bulk_ingest ...
│   └── bulk_hwp_to_hwpx.py              # 서버H COM 변환 스크립트 (Windows 전용)
├── tests/
│   ├── test_entity_classify.py
│   ├── test_frontmatter.py
│   ├── test_idempotency.py               # 같은 sha256이면 skip 검증
│   ├── test_reconvert.py                 # Phase 2
│   └── test_mcp_tools.py                 # Phase 2
└── data/                                 # gitignore — 실제 원본·MD·색인 저장
    ├── raw/                              # HWPX·HWP·PDF 원본
    ├── md/                               # 변환 결과 MD
    ├── fetch-log/
    │   ├── checksums.db                  # 문서별 sha256·버전·포맷 추적
    │   ├── failed.jsonl
    │   ├── hwp-queue.jsonl
    │   ├── pdf-queue.jsonl
    │   └── daily-YYYYMMDD.jsonl          # 일일 증분 로그
    └── govpress.db                       # Phase 2: SQLite FTS5 + 청크 메타
```

---

## 4. 체크포인트 구조 (중요)

Phase 1은 **단일 탈출 조건이 아니라 세 개 마일스톤 + 비상 호출**로 구성된다. 각 마일스톤 완료 시 Codex는 **자동으로 다음 마일스톤으로 진행하지 말고**, 멈춰서 사람 승인을 받는다. 사람 승인 없이 마일스톤을 건너뛴 경우는 즉시 되돌린다.

모든 마일스톤 미달 상태의 커밋은 메시지 앞에 `WIP:` 접두사.

### 4.1 마일스톤 M1 — 스모크 10건 (목표: 토요일 오전 종료)

**범위**: 단일 날짜(기본 `2026-04-10`), 최대 10건.

Codex는 M1을 완료하고 아래 전부 ✅ 되면 **멈추고 보고**. 다음 작업(M2)은 절대 자동 착수 금지.

- [ ] `vendor/gov-md-converter`가 submodule로 등록, `pip install -e vendor/gov-md-converter` 성공
- [ ] `src/govpress_mcp/vendored/policy_briefing.py` 복사 완료 + 상단 `# Source: GovPress_PDF_MD@<git-sha> ...` 주석
- [ ] `list_items(date(2026,4,10))` → `primary_hwpx` 있는 것 10건 선택 → 다운로드 → `data/raw/2026/04/{news_item_id}.hwpx` 저장 (sha256 기록)
- [ ] 같은 10건에 대해 `convert_hwpx` → `data/md/2026/04/{news_item_id}.md` 저장 (frontmatter 포함)
- [ ] Idempotency: 같은 날짜로 재실행 시 sha256 동일분은 `SKIP: already fetched, sha256=...` 로그 10줄 정확히 출력
- [ ] `pytest -q`로 `tests/test_entity_classify.py` · `tests/test_frontmatter.py` · `tests/test_idempotency.py` 3개 통과
- [ ] 로그·커밋·frontmatter에서 `GOVPRESS_POLICY_BRIEFING_SERVICE_KEY` 전수 grep 0건
- [ ] `api2.govpress.cloud` 접속 로그 0건 (`FORBIDDEN_HOSTS` 훅 발동 증거는 있어도 됨)

**보고 형식** (Codex가 멈추면서 출력):
```
M1 완료. 10건 스모크 성공. 승인 대기.
- 대상 날짜: 2026-04-10
- 성공: 10건, skip: {hwp_legacy: N, no_primary_hwpx: N}
- tests: 3/3 pass
- 서비스키 노출 검사: clean
사람이 data/md/2026/04/*.md 내용을 확인하고 "M2 진행"을 지시해 주세요.
```

### 4.2 마일스톤 M2 — 1개월 리허설 (목표: 토 오후~일 오전 종료)

**범위**: `2026-03-01 ~ 2026-03-31` 전 일자. **사람 승인 후에만 착수**.

**기준 (2026-04-18 M2 실측 반영 후 개정)**:
- [ ] 대상 건수 대비 HWPX 성공률 ≥95% (hwp_legacy·pdf_queue 건은 제외하고 산출)
- [ ] skip 분포:
  - `hwp_legacy` <5%
  - `pdf_queue` (no_primary_hwpx + hwpx_html_error_page + hwpx_empty_payload 합산): 기준 없음, 참고용 카운트만
  - `odt_only` / `no_attachments`: 기준 없음, 참고용 카운트만
  - `conversion_failed` (HWPX 변환 실패) <1%
- [ ] 중위 처리 시간 (다운로드+변환) < 5초/건
- [ ] 429/503 재시도 성공률 ≥99%
- [ ] 디스크 사용량 증가치가 이전 실행 대비 ±60% 이내 (절대 예측치 대비가 아님; M2 실측 raw +3.11GB를 기준점으로 삼음)
- [ ] `docs/rehearsal-report.md`에 위 수치 전부 기록
- [ ] 다운로드 실패 유형별 건수 집계: `hwpx_html_error_page` / `hwpx_empty_payload` / `connection_error` / 기타

**보고 형식**:
```
M2 완료. 1개월 리허설 성공. 5년 백필 승인 대기.
- 범위: 2026-03-01 ~ 2026-03-31
- HWPX 성공률: XX.X%, 중위 처리시간: X.Xs
- skip 분포: hwp_legacy X%, pdf_queue Y%, odt_only/기타 Z%, conversion_failed W%
- 다운로드 실패: hwpx_html_error_page N건, hwpx_empty_payload M건
- 디스크 증가: raw +X.XGB, md +X.XGB
사람이 rehearsal-report.md를 확인하고 "M3 진행"을 지시해 주세요.
```

M2 어느 한 조건이라도 실패하면 자동 M3 착수 금지. 해결책을 제시하고 멈춘다.

### 4.3 마일스톤 M3 — 5년 백필 + 일일 증분 (목표: 4~5월)

**범위**: `2021-04-18 ~ 2026-04-18` + 그 이후 일일 증분. **사람 승인 후에만 착수**.

- [ ] 5년 백필 전량 완료 (실행 일정 2~4주)
- [ ] HWPX 트랙 MD 개수가 korea.kr 공식 기관별 목록과 ±5% 이내 (`docs/phase1-report.md`에 기관별 diff 포함)
- [ ] `data/fetch-log/hwp-queue.jsonl`에 M3 기간 중 `hwp_legacy` 건 전량 기록 (HWP 파일 저장 + 큐잉)
- [ ] `data/fetch-log/pdf-queue.jsonl`에 M3 기간 중 pdf_queue 건 전량 기록
- [ ] systemd timer로 일일 증분 등록 + 7일 연속 정상 동작 (매일 06:00 KST)
- [ ] `docs/phase1-report.md` 작성:
  - 전체 대상 건수, HWPX 성공 건수, skip 분포
  - hwp-queue 건수 (M3.5 입력 규모), pdf-queue 건수 (M5 입력 규모)
  - 기관별 MD 개수 vs 공식 목록 diff 표
  - 평균 처리 시간, 실패 건 목록
- [ ] 리포 루트에 `LICENSE-data` 파일 생성

**M3에서 `hwp_legacy` 건 처리 방식 (기존 skip에서 변경):**
- `is_zip_container=False` 감지 시 → HWP 파일 **다운로드 + 저장** (`data/raw/{yyyy}/{mm}/{news_item_id}.hwp`)
- `hwp-queue.jsonl`에 append:
  ```json
  {"news_item_id": "...", "approve_date": "YYYY-MM-DD", "reason": "hwp_legacy", "hwp_path": "data/raw/yyyy/mm/ID.hwp"}
  ```
- MD 생성 없이 skip. 실제 변환은 M3.5(서버H) + M4(재처리)에서 수행.

M3 완료 = HWPX 백필 + 큐 구축 완료. Codex는 멈추고 사람에게 반환.

### 4.3.5 마일스톤 M3.5 — 단일 패스 수집 + COM 변환 (2026-04-19 재설계)

**M3.5는 두 단계로 구성된다.**

#### 단계 1 — 단일 패스 수집 (서버W, Codex 실행)

M3에서 HWPX로 처리된 91,086건은 checksums.db로 skip. 나머지 item에 대해 `select_best_attachment()`로 최우선 포맷을 선택해 단 1회 다운로드.

```bash
# 기존 M3.5 HWP 수집 중단 후 부분 상태 정리 먼저
# 이후 새 단일 패스 실행
python -m govpress_mcp.bulk_ingest \
  --date-range 2021-04-18..2026-04-18 \
  --data-root /home/wavel/projects/govpress-mcp/data \
  --log-json data/fetch-log/single-pass.jsonl
```

완료 후 보고:
- hwp-queue.jsonl 총 건수 (hwp_legacy + no_primary_hwpx_hwp_attachment 합산)
- pdf-queue.jsonl 최종 건수 (HWPX/HWP 모두 없는 건만)
- 디스크 증가분

#### 단계 2 — HWP → HWPX COM 변환 (서버H, 사람이 직접 실행)

`scripts/README-hwp-to-hwpx.md` 절차서 참고.

1. 서버W `hwp-queue.jsonl` 건수 최종 확인
2. 서버W → 서버H: HWP 파일 전송 (rsync/scp/UNC)
3. 서버H: `python bulk_hwp_to_hwpx.py --input <hwp폴더> --output <hwpx폴더>`
4. 서버H → 서버W: HWPX 파일 업로드
5. M4 착수 지시

완료 기준: 변환 성공률 ≥90%, `hwp_convert_errors.jsonl` 저장.

### 4.4 마일스톤 M4 — hwp-queue 재처리 (서버W, 사람 승인 후)

`hwp-queue.jsonl`의 각 `news_item_id`에 대해 M3.5에서 생성된 `.hwpx`를 찾아 MD 생성.

```bash
python -m govpress_mcp.bulk_ingest \
  --from-hwp-queue data/fetch-log/hwp-queue.jsonl \
  --data-root /home/wavel/projects/govpress-mcp/data
```

- `.hwpx` 존재 → `convert_hwpx()` → MD (`source_format: hwpx`)
- `.hwpx` 없음 → `hwpx_missing` 사유로 `failed.jsonl` 기록

완료 기준: hwp-queue 전량 처리, `docs/m4-hwp-report.md` 작성.

### 4.5 마일스톤 M5 — PDF 백필 (서버W, 구 M4)

`pdf-queue.jsonl` 중 **M3.5 패스 A에서 HWP 구조 실패한 잔여분**만 처리. 즉 `no_primary_hwpx` 중 실제로 HWP도 없는 건 + `hwpx_html_error_page` + `hwpx_empty_payload` 건.

`prompts/bulk_ingest_phase1_m4.md` 참고 (파일명은 m4이나 실제 단계는 M5).

### 4.6 체크포인트 의무 정리

| 지점 | 행동 주체 | 사람 행동 |
|---|---|---|
| M1 완료 | Codex 멈춤 | MD 검수 → "M2 진행" |
| M2 완료 | Codex 멈춤 | 리허설 리포트 검토 → "M3 진행" |
| M3 완료 | Codex 멈춤 | phase1-report.md 검토 → M3.5 착수 |
| M3.5 완료 | **사람 직접** | 업로드 확인 → "M4 진행" Codex 지시 |
| M4 완료 | Codex 멈춤 | m4-hwp-report.md 검토 → "M5 진행" |
| M5 완료 | Codex 멈춤 | m5-report.md 검토 → Phase 2 Claude 세션 |

### 4.7 비상 호출 (마일스톤과 무관하게 즉시 중단)

아래 중 **하나라도** 감지되면 Codex는 실행을 즉시 멈추고 상태를 보고한다. 자체 판단으로 우회하지 말 것.

- `api2.govpress.cloud`로 HTTP 시도 감지 (`FORBIDDEN_HOSTS` 훅 로그)
- 서비스키(`GOVPRESS_POLICY_BRIEFING_SERVICE_KEY` 실제 값)가 stdout·로그 파일·커밋 diff·frontmatter 어디든 출력됨
- 429 또는 503이 한 시간 이상 지속 (단일 키 과용 추정)
- 디스크 사용량 600GB 초과 (raw 250GB 실측 기준, 색인 레이어 추가 고려)
- `is_zip_container=True`인데 `convert_hwpx`가 실패하는 비율이 5% 초과 (변환 엔진 회귀)
- `/mnt/c/...` 경로에 데이터가 기록되려는 시도

비상 호출 시 보고 형식:
```
EMERGENCY STOP: <조건>
- 감지 시각: YYYY-MM-DD HH:MM KST
- 진행 중이던 단계: M1/M2/M3
- 영향 범위: <파일·건수>
- 자동 복구 시도 여부: NO (사람 판단 대기)
```

---

## 5. 절대 하지 말 것

- 기존 결정을 임의로 재해석 (특히 경로·포맷·rate limit)
- 서비스키를 로그·커밋·주석·frontmatter에 노출
- `api2.govpress.cloud`에 요청
- `/mnt/c/...` Windows 경로에 데이터 저장
- `PolicyBriefingCache.warm_item()` 호출 (저장 레이아웃이 충돌)
- HWP(구버전 바이너리)를 govpress-converter로 직접 변환 시도 (HWP는 hwp-queue 큐잉만, 변환은 M3.5 서버H COM)
- PDF를 M3.5 단일 패스에서 변환 시도 (PDF는 pdf-queue 큐잉만, 변환은 M5)
- select_best_attachment() 없이 HWPX만 시도하고 나머지를 pdf-queue에 일괄 투기
- `no_primary_hwpx_hwp_attachment` 건을 `client.download_item_hwpx()`로 다운로드 시도 (item.attachments 직접 순회 필요)
- 의존성을 불필요하게 늘리기 (pure Python + 표준 라이브러리 + `govpress-converter` + 필요 시 `pydantic`/`tenacity` 정도면 충분)
- **Phase 2 추가 금지**:
  - Qdrant 볼륨·SQLite DB를 `/mnt/c/...` 경로에 마운트 (반드시 `/home/wavel/...` WSL 네이티브)
  - derive_hot.py에서 임베딩을 OpenAI API로 전송 (BGE-M3 TEI 셀프호스팅만 사용)
  - MCP 도구 응답에 라이선스 footer 삽입 (frontmatter `source_url`로 대체, §8.3.5 참고)
  - reconvert.py 전량 실행 — converter XML 파서 개선 전에는 실행 금지 (현재 249건 전량 실패 확인됨)

---

## 6. 질문을 해야 할 상황

아래 경우는 구현 전에 사람에게 확인:

- Govpress 레포에서 예상과 다른 시그니처 발견
- `approve_date` 파싱이 일관되지 않음 (타임존 포함 여부)
- HWPX인데 `is_zip_container=False`인 사례가 10% 이상
- 특정 기관의 첨부 파일 URL이 반복적으로 403·404
- entity_type 판정 룰이 모호한 department (예: 공단·공사·청 이름)

---

## 7. 참고 문서

- 전체 아키텍처: `C:\Users\wavel\OneDrive\문서\Claude\Projects\보도자료 PDF-MD 변환\데이터-저장-아키텍처.md`
- MCP 도구 명세: 같은 폴더 `Govpress-MCP-구현명세.md`
- 버전 비교 실험: `silent-overwrite-검증실험.md`
- Phase 1 절차서: `보도자료 PDF-MD 변환\Phase1-실행-절차서.md`
- **Phase 2 절차서**: `보도자료 PDF-MD 변환\Phase2-실행-절차서.md` ← Phase 2 작업 시 필독

---

## 8. Phase 2 — 색인·서빙 레이어 (2026-04-21 착수)

### 8.1 Phase 1 최종 현황 (참고)

| 항목 | 수치 |
|---|---|
| 총 MD | 129,901건 (커밋 aca5c55) |
| source_format=hwpx | 128,884 |
| source_format=hwp | 53 |
| source_format=pdf | 1,025 |
| raw 저장량 | 250.30 GiB |
| MD 저장량 | 1.05 GiB |
| 일일 증분 timer | govpress-mcp-daily.timer, 매일 03:00 KST |

영구 skip: hwp_distribution_only 52 / html_error_page 163 / empty_payload 12 = 227건

### 8.2 task #32 — reconvert.py 현황 (전량 실행 보류)

구현 완료. dry-run 10건 전량 실패. 전량 실행은 govpress-converter XML 파서 개선 후로 보류.

**실패 분류**:

| 유형 | 건수 | 조치 |
|---|---|---|
| hwpx_invalid_token | 223 | converter 파서 개선 후 재시도 |
| hwpx_syntax_error | 16 | converter 파서 개선 후 재시도 |
| hwpx_invalid_file (비zip 6 + central_dir손상 1) | 7 | 비zip 분기 처리 필요 |
| hwpx_unpack_error / hwpx_other | 3 | 조사 필요 |
| PDF 10건 (HTML·HWP위장·DOCUMENTSAFER·깨진PDF) | 10 | 소스 자체 불량, 영구 skip |

비zip 6건 목록: `data/fetch-log/reconvert-hwpx-notzip-6.txt`

**재실행 조건**: converter HWPX XML 파서 개선 릴리즈 후 `--source-format hwpx` 로만 재실행. PDF 10건 제외.

### 8.3 T1 — derive_hot.py 스펙

#### 8.3.1 목적

`data/md/` 전량을 청크로 분할 → BGE-M3 임베딩 → Qdrant upsert + SQLite FTS5 색인 구축.
**불변 원칙**: Hot은 Warm(MD)으로부터 언제든 결정론적으로 재생성 가능해야 한다.

#### 8.3.2 청킹 규칙

- 단위: 문단 기반, 최대 512 토큰
- overlap: 64 토큰
- 청크 ID: `{news_item_id}_{chunk_index:04d}`
- payload 보존: `news_item_id`, `approve_date`, `department`, `entity_type`, `chunk_index`, `chunk_total`

#### 8.3.3 Qdrant 컬렉션

```python
collection_name = "briefing_chunks"
# 차원: 1024 (BGE-M3)
# 거리: Cosine
# HNSW: m=16, ef_construct=200
# payload 인덱스: news_item_id, approve_date, entity_type, department
```

#### 8.3.4 SQLite FTS5

```sql
-- data/govpress.db
CREATE VIRTUAL TABLE IF NOT EXISTS briefing_fts USING fts5(
    news_item_id UNINDEXED,
    chunk_index  UNINDEXED,
    body,
    tokenize='unicode61 trigram'
);
```

mecab-ko 도입 여부: 100건 샘플 recall 실험 후 결정 (차이 ≥5%p 이면 도입).

#### 8.3.5 임베딩 — TEI 엔드포인트

```
http://localhost:8080  (TEI 컨테이너, BGE-M3, RTX 3080)
배치 크기: 64
```

OpenAI 등 외부 임베딩 API 사용 금지.

#### 8.3.6 CLI

```bash
# 전량 색인 (초기 1회)
python -m govpress_mcp.derive_hot \
  --data-root /home/wavel/projects/govpress-mcp/data \
  --qdrant-url http://localhost:6333 \
  --tei-url http://localhost:8080 \
  --db /home/wavel/projects/govpress-mcp/data/govpress.db \
  --checkpoint 1000

# 일일 증분 (govpress-mcp-daily.service 에서 bulk_ingest 직후 호출)
python -m govpress_mcp.derive_hot --incremental \
  --data-root /home/wavel/projects/govpress-mcp/data \
  --qdrant-url http://localhost:6333 \
  --tei-url http://localhost:8080 \
  --db /home/wavel/projects/govpress-mcp/data/govpress.db
```

idempotent 보장: chunk_id 기준 upsert (재실행 무해).

체크포인트 파일: `data/fetch-log/derive-hot-checkpoint.json` (마지막 처리 MD 경로 + 타임스탬프).

완료 후 `docs/derive-hot-report.md` 작성:
- 처리 MD 건수, 총 청크 수, 임베딩 소요 시간
- Qdrant 컬렉션 벡터 수
- FTS5 row 수
- 실패 건 (청킹 오류 등)

### 8.4 T2 — Docker-compose 스택

```yaml
# 볼륨은 반드시 /home/wavel/... WSL 네이티브 경로

services:
  qdrant:
    image: qdrant/qdrant:latest
    volumes:
      - /home/wavel/projects/govpress-mcp/data/qdrant:/qdrant/storage
    ports: ["6333:6333"]

  tei:
    image: ghcr.io/huggingface/text-embeddings-inference:latest
    command: --model-id BAAI/bge-m3
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    ports: ["8080:80"]

  redis:
    image: redis:7-alpine
    command: redis-server --maxmemory 1gb --maxmemory-policy allkeys-lru
    ports: ["6379:6379"]

  mcp-server:
    build: .
    env_file: .env
    volumes:
      - /home/wavel/projects/govpress-mcp/data:/app/data:ro
    ports: ["8000:8000"]
    depends_on: [qdrant, tei, redis]

networks:
  default:
    name: govpress_mcp_net
```

### 8.5 T3 — MCP 8개 도구

| # | 도구명 | 설명 | 응답 상한 |
|---|---|---|---|
| 1 | `search_briefing` | 의미 검색 (Qdrant + BGE-M3) | 상위 50건 요약 |
| 2 | `get_briefing` | 단건 전문 조회 (full MD) | 평균 15KB |
| 3 | `list_briefings` | 날짜·부처·entity_type 필터 목록 | 100건 |
| 4 | `fts_search` | 키워드 전문 검색 (FTS5) | 상위 50건 |
| 5 | `compare_versions` | 동일 문서 개정 전후 비교 ⚠️ **실험** | 시간축 10건 |
| 6 | `cross_check_ministries` | 동일 주제 부처별 입장 비교 | 부처 5개 |
| 7 | `trace_policy` | 정책 흐름 시계열 추적 | 노드 50개 |
| 8 | `get_stats` | 수집 현황 통계 | 단일 JSON |

평균 응답 < 50KB 목표. 모든 응답에 `source_url` 포함 (korea.kr 원문 링크). 응답 footer에 라이선스 문구 삽입 금지.

`compare_versions` ⚠️: silent-overwrite 실험 관찰 중. 6개월 후 L2/L3 변경 빈도 기준으로 존속 판단.

### 8.6 Phase 2 체크포인트

| 지점 | 행동 주체 | 완료 기준 |
|---|---|---|
| T1 완료 | Codex 멈춤 | derive-hot-report.md 작성 → 사람 검토 |
| T2 완료 | Codex 멈춤 | 스택 7일 안정 → 사람 확인 |
| T3 완료 | Codex 멈춤 | pytest 통과 + 응답 <50KB + 사람 검토 |
| T4 완료 | Codex 멈춤 | mcp.govpress.cloud 스모크 테스트 통과 |
| task #32 재실행 | converter 파서 개선 후 | 별도 지시 대기 |
