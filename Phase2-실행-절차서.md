# Phase 2 실행 절차서 — Govpress MCP 색인·서빙 레이어

작성: 2026-04-21  
현재 상태: **Phase 2 착수** (Phase 1 완료, task #32 reconvert.py 진행 중)

---

## 전체 흐름 한눈에 보기

```
[완료] Phase 1 — 129,901건 MD 생성 (hwpx 128,884 / hwp 53 / pdf 1,025)
  ↓
[지금] task #32 — reconvert.py (conversion_failed 259건 재처리)
  ↓
[T1] derive_hot.py — MD → Qdrant 청크 + SQLite FTS5 색인
  ↓
[T2] Docker-compose 스택 구성 — Qdrant + TEI(BGE-M3) + Redis + SQLite + MCP 서버
  ↓
[T3] MCP 8개 도구 구현 및 테스트
  ↓
[T4] Cloudflare Tunnel 연결 + mcp.govpress.cloud 공개
  ↓
[T5] policy-briefing-kr 레포 public 전환 판단
```

---

## Phase 1 → Phase 2 전환 현황

| 조건 (§8.3) | 상태 |
|---|---|
| ① 5년 백필 전량 완료 | ✅ 129,901건 |
| ② MD 수 ±5% 검증 | ⏳ 미확인 (Phase 2 착수 후 확인 예정) |
| ③ 7일 연속 일일 증분 | ⏳ timer 설정 완료, 안정 관찰 중 |
| ④ phase1-report.md | ✅ 커밋 aca5c55 |

7일 대기 없이 즉시 Phase 2 착수 결정 (2026-04-21).

---

## Phase 1 최종 통계 (참고)

| 항목 | 수치 |
|---|---|
| 총 MD | 129,901건 |
| source_format=hwpx | 128,884건 |
| source_format=hwp | 53건 |
| source_format=pdf | 1,025건 |
| raw 저장량 | 250.30 GiB |
| MD 저장량 | 1.05 GiB |
| 영구 skip | 227건 (배포전용 52 + html_error 163 + empty 12) |
| reconvert 대상 | 259건 (M3 248 + M4 1 + M5 10) |

---

## task #32 — reconvert.py (구현 완료, 전량 실행 보류)

### 상태 (2026-04-21 분석 완료)

구현은 완료됐지만 dry-run 샘플 10건 전량 실패. 전량 실행은 converter 파서 개선 후로 보류.

### 실패 원인 분석

**PDF 10건 — 입력 품질 문제 (현시점 불가)**

| 유형 | 건수 | 비고 |
|---|---|---|
| 정상 PDF (파싱 오류) | 1 | VeraPDFParserException, invalid dictionary |
| HTML로 위장된 .pdf | 3 | |
| HWP/HWPX로 위장된 .pdf | 2 | |
| DOCUMENTSAFER_* 비표준 바이너리 | 4 | |

→ 10건 전량 소스 자체 문제. converter 개선으로 해결 불가. 영구 보류 처리.

**HWPX 249건 — converter XML 파서 개선 필요**

| 오류 유형 | 건수 | 조치 |
|---|---|---|
| hwpx_invalid_token | 223 | converter XML 파서 개선 후 재시도 |
| hwpx_syntax_error | 16 | converter XML 파서 개선 후 재시도 |
| hwpx_invalid_file (비zip 6 + central_dir손상 1) | 7 | 비zip 분기 처리 또는 영구 skip |
| hwpx_unpack_error | 1 | 조사 필요 |
| hwpx_other | 2 | 조사 필요 |

비zip HWPX 6건 목록: `data/fetch-log/reconvert-hwpx-notzip-6.txt`

### 산출물

- `src/govpress_mcp/reconvert.py` — CLI 구현 완료
- `tests/test_reconvert.py`
- `docs/reconvert-report.md`
- `docs/reconvert-pdf-10.md`
- `docs/reconvert-hwpx-249.md`
- `data/fetch-log/reconvert-hwpx-notzip-6.txt`

### 재실행 조건

govpress-converter에서 HWPX XML 파서 개선 릴리즈 후:

```bash
python -m govpress_mcp.reconvert \
  --data-root /home/wavel/projects/govpress-mcp/data \
  --source-format hwpx \
  --log-json data/fetch-log/reconvert-$(date +%Y%m%d).jsonl
```

PDF 10건은 재실행 대상에서 제외 (입력 파일 자체 불량).

---

## T1 — derive_hot.py: Warm → Hot 색인 파이프라인

### 목적

`data/md/` 의 MD 파일 전량을 청크로 분할해 Qdrant 벡터 색인 + SQLite FTS5 키워드 색인을 구축한다. Hot 레이어는 Warm(MD)으로부터 언제든 결정론적으로 재생성 가능해야 한다.

### 청킹 전략

| 항목 | 설계 |
|---|---|
| 단위 | 문단 기반, 최대 512 토큰 |
| overlap | 64 토큰 |
| 메타 보존 | `news_item_id`, `approve_date`, `department`, `entity_type`, `chunk_index`, `chunk_total` |
| 청크 ID | `{news_item_id}_{chunk_index:04d}` |

### Qdrant 컬렉션

```
컬렉션명: briefing_chunks
차원: 1024 (BGE-M3)
거리: Cosine
HNSW: m=16, ef_construct=200
payload 필터: news_item_id, approve_date, entity_type, department
```

### SQLite FTS5

```sql
CREATE VIRTUAL TABLE briefing_fts USING fts5(
    news_item_id UNINDEXED,
    chunk_index UNINDEXED,
    body,
    tokenize='unicode61 trigram'
);
```

mecab-ko는 100건 샘플 실험 후 recall 차이 ≥5%p 이면 도입, 미만이면 trigram 유지.

### BGE-M3 임베딩

```yaml
# TEI 컨테이너 (docker-compose)
image: ghcr.io/huggingface/text-embeddings-inference:latest
model: BAAI/bge-m3
device: cuda (RTX 3080 바인딩)
batch_size: 64
max_client_batch_size: 256
```

### 실행 방식

```bash
# 전량 색인 (초기 1회)
python -m govpress_mcp.derive_hot \
  --data-root /home/wavel/projects/govpress-mcp/data \
  --qdrant-url http://localhost:6333 \
  --tei-url http://localhost:8080 \
  --db /home/wavel/projects/govpress-mcp/data/govpress.db \
  --checkpoint 1000

# 일일 증분 (systemd timer에서 bulk_ingest 직후 호출)
python -m govpress_mcp.derive_hot --incremental
```

idempotent 보장: `chunk_id` 기준 upsert (중복 재처리 무해).

---

## T2 — Docker-compose 스택 구성

### 서비스 구성

```yaml
# docker-compose.yml (서버W WSL 네이티브 경로 사용)
services:
  qdrant:
    image: qdrant/qdrant:latest
    volumes:
      - /home/wavel/projects/govpress-mcp/data/qdrant:/qdrant/storage
    ports:
      - "6333:6333"

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
    ports:
      - "8080:80"

  redis:
    image: redis:7-alpine
    command: redis-server --maxmemory 1gb --maxmemory-policy allkeys-lru
    ports:
      - "6379:6379"

  mcp-server:
    build: .
    env_file: .env
    volumes:
      - /home/wavel/projects/govpress-mcp/data:/app/data:ro
    ports:
      - "8000:8000"
    depends_on: [qdrant, tei, redis]

networks:
  default:
    name: govpress_mcp_net
```

볼륨은 반드시 `/home/wavel/...` WSL 네이티브 경로. `/mnt/c/...` 금지 (I/O 성능 급락).

---

## T3 — MCP 8개 도구 구현

### 도구 목록

| # | 도구명 | 설명 | 응답 상한 |
|---|---|---|---|
| 1 | `search_briefing` | 의미 검색 (Qdrant + BGE-M3) | 상위 50건 요약 |
| 2 | `get_briefing` | 단건 전문 조회 (full MD) | 평균 15KB |
| 3 | `list_briefings` | 날짜·부처·entity_type 필터 목록 조회 | 100건 |
| 4 | `fts_search` | 키워드 전문 검색 (SQLite FTS5) | 상위 50건 |
| 5 | `compare_versions` | 동일 문서 개정 전후 비교 | 시간축 10건 |
| 6 | `cross_check_ministries` | 동일 주제 부처별 입장 비교 | 부처 5개 |
| 7 | `trace_policy` | 정책 흐름 시계열 추적 | 노드 50개 |
| 8 | `get_stats` | 수집 현황 통계 (건수·날짜·포맷 분포) | 단일 JSON |

**참고**: `compare_versions`는 실험 배지 부착 (silent-overwrite 관찰 결과에 따라 존속 판단).

### 응답 규격

- 평균 응답 < 50KB 목표
- 모든 응답에 `source_url` (korea.kr 원문 링크) 포함
- 라이선스 고지: 응답 footer 없음, frontmatter `source_url`로 대체

### 보안

- 엔드포인트: `mcp.govpress.cloud` 완전 공개 (인증 없음)
- Cloudflare WAF rate limit: IP당 10 req/min (기본값, 관찰 후 조정)
- 도구별 응답 크기 상한으로 과도한 bulk 추출 방지

---

## T4 — Cloudflare Tunnel 연결

```bash
# 서버W에서
cloudflared tunnel route dns <TUNNEL_ID> mcp.govpress.cloud
cloudflared tunnel run --url http://localhost:8000 <TUNNEL_ID>
```

또는 `cloudflared` systemd 서비스로 등록.

스모크 테스트:
```bash
curl https://mcp.govpress.cloud/tools | jq '.tools | length'
# → 8
```

---

## T5 — policy-briefing-kr 레포 public 전환

전환 기준 (Phase 2 완료 시 별도 판단):

- MCP 서버 7일 안정 운영 확인
- MD + frontmatter 샘플 퀄리티 검토
- `LICENSE-data` (공공누리 1유형) 루트 배치 확인
- README에 출처·라이선스·재사용 안내 포함 확인

**전환 시 공개 범위**: MD + frontmatter + 스크립트 + 스키마. HWPX 원본·임베딩 원본·운영 로그·`.env`는 비공개 유지.

---

## 인프라 볼륨 추정 (Phase 1 실측 기반)

| 레이어 | 예상 크기 | 비고 |
|---|---|---|
| raw (HWPX·HWP·PDF) | 250.30 GiB (실측) | 서버W 로컬 |
| MD | 1.05 GiB (실측) | Git LFS (MD만) |
| Qdrant 벡터 + HNSW | ~15~21 GiB | 129,901건 × 평균 5청크 × 1024-dim |
| SQLite FTS5 | ~3~7 GiB | trigram 인덱스 포함 |
| SQLite 메타 | ~1 GiB | checksums + 청크 메타 |
| Redis 핫셋 | 1 GiB (상한 고정) | LRU 500건 |
| **합계** | ~271~281 GiB | 서버W 디스크 여유 충분 |

---

## 단계별 Codex 지시 요약

| 단계 | Codex에 보낼 메시지 첫 줄 |
|---|---|
| task #32 | "reconvert.py 구현 계획 승인. dry-run 10건 먼저 실행하고 결과 보고해라." |
| T1 착수 | "reconvert 완료. derive_hot.py 설계 및 구현 착수해라. AGENTS.md Phase 2 §T1 읽어라." |
| T2 착수 | "derive_hot 완료. docker-compose 스택 구성해라." |
| T3 착수 | "스택 구동 확인. MCP 8개 도구 구현 착수해라." |
| T4 착수 | "도구 구현 완료. Cloudflare Tunnel 연결하고 스모크 테스트 실행해라." |

---

## 완료 기준 (Phase 2 → 운영 전환)

- [ ] reconvert.py: 259건 중 재처리 성공률 확인 (여전히 실패 건은 별도 리포트)
- [ ] derive_hot.py: 129,901건 전량 청킹·임베딩·색인 완료
- [ ] FTS5: `unicode61 trigram` 기본 적용 (mecab-ko 실험 결과에 따라 교체)
- [ ] docker-compose 스택: 7일 안정 운영
- [ ] MCP 8개 도구: pytest 통과 + 응답 < 50KB 확인
- [ ] `mcp.govpress.cloud` 공개 접속 확인
- [ ] `docs/phase2-report.md` 작성

---

## 주의사항

- **볼륨 경로**: 모든 컨테이너 볼륨은 `/home/wavel/...` WSL 네이티브 경로. `/mnt/c/...` 절대 금지.
- **Hot 재생성 원칙**: Qdrant·FTS5는 `data/md/` 에서 언제든 재구축 가능해야 함. 색인만 삭제해도 데이터 손실 없음.
- **compare_versions 실험 배지**: 6개월 관찰 후 존속 여부 판단 (L2/L3 변경 빈도 기준).
- **일일 증분 연동**: `derive_hot.py --incremental`은 `govpress-mcp-daily.service`에서 bulk_ingest 직후 호출.
