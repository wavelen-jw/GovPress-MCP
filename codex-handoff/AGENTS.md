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
- 작업 디렉토리 루트: `/home/USER/govpress-mcp/` (`USER`는 실제 사용자명으로 치환). **절대 `/mnt/c/...` 금지** — Windows 드라이브 I/O 성능 문제.
- 데이터 디렉토리: `/home/USER/govpress-mcp/data/{raw,md,fetch-log}`
- Python ≥ 3.10 (변환 엔진 요구사항)
- PDF 변환이 필요한 경우에만 Java 11+ (Phase A는 HWPX만 다루므로 불필요)

### 1.2 원본 포맷

- **HWPX만 다룬다**. HWP(구버전)·PDF는 스킵(`primary_hwpx is None`이면 continue).
- 기존 문서에 "PDF"로 적힌 부분은 모두 HWPX로 해석.

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
/home/USER/govpress-mcp/data/
├── raw/{yyyy}/{mm}/{news_item_id}.hwpx      # 원본 HWPX
├── md/{yyyy}/{mm}/{news_item_id}.md         # 변환 결과 + frontmatter
└── fetch-log/
    ├── checksums.db                          # SQLite: news_item_id → sha256, fetched_at
    └── failed.jsonl                          # 변환 실패 재시도 큐
```

`yyyy`/`mm`는 `approve_date` 기준.

### 1.7 Frontmatter 필수 필드

```yaml
---
id: <news_item_id>
title: <item.title>
department: <item.department>
approve_date: <ISO 8601>
entity_type: central | metro | local
original_url: <item.original_url>
sha256: <raw HWPX의 sha256>
revision: 1
extracted_by: <govpress-converter version>+<gov-md-converter git SHA>
raw_path: data/raw/yyyy/mm/{news_item_id}.hwpx
---
```

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
│       ├── bulk_ingest.py                # 메인 루프
│       ├── entity_classify.py            # department → entity_type
│       ├── frontmatter.py                # 생성·파싱
│       ├── paths.py                      # 저장 경로 규약
│       ├── ratelimit.py                  # 동시성·backoff
│       └── checksums.py                  # sha256 비교, SQLite 추적
├── scripts/
│   └── run_bulk_ingest.sh                # env 로드 + python -m govpress_mcp.bulk_ingest ...
├── tests/
│   ├── test_entity_classify.py
│   ├── test_frontmatter.py
│   └── test_idempotency.py               # 같은 sha256이면 skip 검증
└── data/                                 # gitignore — 실제 원본·MD 저장
    ├── raw/
    ├── md/
    └── fetch-log/
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

- [ ] 대상 건수 대비 성공률 ≥95% (HWP 구버전 skip은 성공에 포함하지 않고 별도 카운트)
- [ ] skip 분포: `hwp_legacy` <5%, `no_primary_hwpx` <2%, `conversion_failed` <1%
- [ ] 평균 처리 시간 (다운로드+변환) < 5초/건
- [ ] 429/503 재시도 성공률 ≥99%
- [ ] 디스크 사용량 증가치가 예측(월 ~2GB 원본+MD)과 ±30% 이내
- [ ] `docs/rehearsal-report.md`에 위 수치 전부 기록

**보고 형식**:
```
M2 완료. 1개월 리허설 성공. 5년 백필 승인 대기.
- 범위: 2026-03-01 ~ 2026-03-31
- 성공률: XX.X%, 중위 처리시간: X.Xs
- skip 분포: hwp_legacy X%, no_primary_hwpx X%, conversion_failed X%
- 디스크 증가: +X.XGB (예측 대비 +/- X%)
사람이 rehearsal-report.md를 확인하고 "M3 진행"을 지시해 주세요.
```

M2 어느 한 조건이라도 실패하면 자동 M3 착수 금지. 해결책을 제시하고 멈춘다.

### 4.3 마일스톤 M3 — 5년 백필 + 일일 증분 (목표: 4~5월)

**범위**: `2021-04-18 ~ 2026-04-18` + 그 이후 일일 증분. **사람 승인 후에만 착수**.

- [ ] 5년 백필 전량 완료 (실행 일정 2~4주)
- [ ] MD 개수가 korea.kr 공식 기관별 목록과 ±5% 이내 (`docs/phase1-report.md`에 기관별 diff 포함)
- [ ] systemd timer로 일일 증분 등록 + 7일 연속 정상 동작 (매일 06:00 KST)
- [ ] `docs/phase1-report.md` 작성:
  - 전체 대상 건수, 성공 건수, skip 분포
  - 기관별 MD 개수 vs 공식 목록 diff 표
  - 평균 처리 시간
  - 누락·재시도 실패 건 목록 (`docs/failed.jsonl` 링크)
- [ ] 리포 루트에 `LICENSE-data` 파일 생성 (공공누리 1유형 전문 + 데이터 소스 구조 + 제3자 재사용 안내)

M3 완료 = **진짜 Phase 1 종료**. Codex는 여기서 멈추고 사람에게 반환. Phase 2(색인·derive_hot.py·Qdrant)는 Claude 세션에서 설계한 뒤 새 프롬프트로 재진입.

### 4.4 체크포인트 의무 정리

| 지점 | Codex 행동 | 사람 행동 |
|---|---|---|
| M1 완료 | **멈추고 보고** | MD 수작업 검수 → "M2 진행" 지시 |
| M2 완료 | **멈추고 보고** | 리허설 리포트 검토 → "M3 진행" 지시 |
| M3 완료 | **멈추고 보고** | phase1-report.md 검토 → Claude 세션으로 이동 |

Codex가 승인 없이 M1→M2 또는 M2→M3로 넘어간 흔적이 발견되면 해당 커밋을 revert하고 해당 마일스톤을 재실행한다.

### 4.5 비상 호출 (마일스톤과 무관하게 즉시 중단)

아래 중 **하나라도** 감지되면 Codex는 실행을 즉시 멈추고 상태를 보고한다. 자체 판단으로 우회하지 말 것.

- `api2.govpress.cloud`로 HTTP 시도 감지 (`FORBIDDEN_HOSTS` 훅 로그)
- 서비스키(`GOVPRESS_POLICY_BRIEFING_SERVICE_KEY` 실제 값)가 stdout·로그 파일·커밋 diff·frontmatter 어디든 출력됨
- HWP 구버전(`is_zip_container=False`) 비율이 전체의 10% 초과 (도메인 가정 붕괴)
- 429 또는 503이 한 시간 이상 지속 (단일 키 과용 추정)
- 디스크 사용량 120GB 초과
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
- HWP(구버전 바이너리)·PDF를 강제로 변환하려 시도 (Phase A 범위 밖)
- 의존성을 불필요하게 늘리기 (pure Python + 표준 라이브러리 + `govpress-converter` + 필요 시 `pydantic`/`tenacity` 정도면 충분)

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

---

## 8. Phase 2 — 색인·MCP 서버 (착수 기준: Phase 1 M3 완료 후)

Phase 1(크롤·변환·저장) 완료 후 Qdrant/FTS5 색인과 MCP 8개 도구 구현을 진행한다.
각 태스크(T1~T3)는 사람 승인 없이 자동 진행 **금지**. 완료 보고 후 대기.

### 8.1 Phase 2 진행 상태 (2026-04-22 기준)

| 태스크 | 내용 | 상태 |
|---|---|---|
| T1 | FTS5 가상 테이블 + SQLite `briefings` 스키마 + `ministry_alias` 초기 데이터 | ✅ 완료 |
| T2 | Qdrant 컬렉션 생성 + BGE-M3/TEI 배치 임베딩 파이프라인 | ✅ 완료 |
| T3 | MCP 8개 도구 구현 (Python `mcp` SDK) | 🔜 착수 예정 |

T3 세부 프롬프트: `codex-handoff/prompts/mcp_tools_phase2.md`

### 8.2 Phase 2 인프라 불변 조건

#### Docker Compose 서비스

```yaml
qdrant:
  image: qdrant/qdrant:v1.17.1          # 버전 고정 — migration 리스크 방지
  ports: ["127.0.0.1:6333:6333"]
  volumes: ["./data/qdrant:/qdrant/storage"]
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:6333/healthz"]
    # /healthz 사용. /health는 Qdrant 1.7.0+ 에서 제거됨 (v1.17.1 기준)
    interval: 30s
    timeout: 5s
    retries: 3

embed:                                   # BGE-M3 임베딩 (TEI)
  image: ghcr.io/huggingface/text-embeddings-inference:turing-1.5
  ports: ["127.0.0.1:18080:80"]
  # 호스트 18080 → 컨테이너 80. 8080은 타 서비스 충돌 방지
  environment:
    MODEL_ID: BAAI/bge-m3
  deploy:
    resources:
      reservations:
        devices: [{driver: nvidia, count: 1, capabilities: [gpu]}]
```

**포트 주의사항 (재협상 금지)**:
- Qdrant 헬스 체크: `/healthz` (`/health`는 Qdrant 1.7.0+에서 제거됨. v1.17.1 기준)
- TEI 외부 포트: `18080` (`8080`은 다른 서비스와 충돌 가능성)
- `EMBED_URL` 환경변수: `http://embed:80` (컨테이너 내부 통신은 포트 80 그대로)

#### 환경 변수 (`.env` 추가 항목)

```
QDRANT_URL=http://qdrant:6333
EMBED_URL=http://embed:80
REDIS_URL=redis://redis:6379
MCP_PORT=8000
```

### 8.3 T3 착수 전 전제조건

- T1: `briefings`, `briefing_ministries`, `ministry_alias`, `statistics` 테이블 DDL + FTS5 가상 테이블 `briefings_fts` 존재 확인
- T2: Qdrant 컬렉션 `briefing_chunks` 존재 확인 + 30만 건 임베딩 완료 확인
- `docker compose ps`로 qdrant/embed/redis 모두 `healthy` 상태 확인
