# Govpress MCP — Codex 시작 가이드

이 폴더(`codex-handoff/`)는 Codex CLI에게 Phase A 구현을 넘기기 위한 한 페이지 핸드오프다.

## 폴더 구성

```
codex-handoff/
├── README-for-codex.md       # 이 파일 (시작 가이드)
├── AGENTS.md                 # 불변 조건 + 실제 API 시그니처 + 탈출 조건
├── bulk_ingest.py            # 스켈레톤 (Codex가 TODO 채움)
└── prompts/
    └── bulk_ingest_phase1.md # 첫 작업 프롬프트
```

---

## 서버W WSL에서 시작하는 순서

### 1) Govpress MCP 프로젝트 초기화

```bash
cd ~/projects                                  # /mnt/c/... 쓰지 마라 — AGENTS.md §1.1
mkdir govpress-mcp && cd govpress-mcp
git init -b main

# 핸드오프 파일을 프로젝트 루트로 복사
cp "/mnt/c/Users/wavel/OneDrive/문서/Claude/Projects/보도자료 PDF-MD 변환/codex-handoff/AGENTS.md" .
mkdir -p src/govpress_mcp scripts tests prompts
cp "/mnt/c/Users/wavel/OneDrive/문서/Claude/Projects/보도자료 PDF-MD 변환/codex-handoff/bulk_ingest.py" src/govpress_mcp/
cp "/mnt/c/Users/wavel/OneDrive/문서/Claude/Projects/보도자료 PDF-MD 변환/codex-handoff/prompts/bulk_ingest_phase1.md" prompts/
```

> `/mnt/c/...` 경로는 **복사할 때만** 사용. 데이터 저장 위치로는 절대 사용 금지.

### 2) 서비스키 준비

```bash
cat > .env <<'EOF'
GOVPRESS_POLICY_BRIEFING_SERVICE_KEY=여기에_키_붙여넣기
EOF
echo ".env" >> .gitignore
echo "data/" >> .gitignore
echo "vendor/gov-md-converter/.venv/" >> .gitignore
```

### 3) Codex 세션 시작

```bash
codex
```

Codex가 뜨면 첫 지시로 아래를 주입:

```
읽어야 할 파일:
  - AGENTS.md (불변 조건, 반드시 준수)
  - prompts/bulk_ingest_phase1.md (이번 작업 지시)
  - src/govpress_mcp/bulk_ingest.py (스켈레톤, TODO를 채워라)

작업: prompts/bulk_ingest_phase1.md 의 탈출 조건을 모두 만족할 때까지 진행.
탈출 조건 미달 시 커밋 메시지에 WIP: 접두사. 완료 시 docs/phase1-report.md 작성.
```

### 4) 사람이 중간에 확인할 체크포인트

- submodule 추가 직후 → `git status`로 `vendor/gov-md-converter` submodule 등록 확인
- `policy_briefing.py` 복사 직후 → 상단 SHA 주석 확인
- 10건 스모크 실행 후 → 실제 MD 파일 frontmatter 눈으로 검토, 민감 정보 유출 없는지
- 재실행 후 → `skip-unchanged` 로그가 정확히 10건인지

### 5) 리뷰 루프

Codex 작업이 끝나면:

1. `git diff main..HEAD` 보고 이 세션(Claude)에 붙여넣기 → 코드 리뷰 요청
2. 수정사항은 다시 Codex에 지시 (또는 직접 수정)
3. Phase 2 착수 결정 시 `prompts/bulk_ingest_phase2.md` 작성 후 반복

---

## Codex가 실수하기 쉬운 지점 (사전 경고)

| 실수 | 원인 | 방지 |
|---|---|---|
| `api2.govpress.cloud` 호출 | 문서에서 언급돼서 유혹 | FORBIDDEN_HOSTS 차단 훅 구현 강제 |
| 서비스키 로그에 노출 | 디버깅 중 편의 | `LOG.info(f"url={url}")` 류 금지, 커밋 전 grep 체크 |
| `/mnt/c/...`에 data 저장 | 경로 하드코딩 실수 | `--data-root` arg 기본값을 `/home/USER/...`로 |
| `PolicyBriefingCache.warm_item` 호출 | Govpress 코드 읽다 유혹 | AGENTS.md §2.2에 명시된 대로 list + download까지만 |
| `govpress-converter` PyPI 공식판 설치 | 자동완성이 안내 | `pip install -e vendor/gov-md-converter` 또는 private wheel만 |
| HWP(구버전) 파일 강제 변환 | `.hwpx` 확장자지만 바이너리가 HWP | `downloaded.is_zip_container` 체크 필수 |

---

## 완료 후 사람이 할 일

- Phase 1 결과(10건) 검수
- 서비스키 rotation (혹시라도 노출됐는지 전수 grep)
- Phase 2 범위 결정 (예: 1개월치 리허설 → 5년 백필)
- Qdrant·BGE-M3·SQLite 색인 레이어 설계로 전환 (derive_hot.py)
