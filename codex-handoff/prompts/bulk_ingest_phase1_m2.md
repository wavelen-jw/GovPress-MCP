# M2 작업 프롬프트 — 1개월 리허설

**이 프롬프트는 M1 완료 + 사람 승인 후에만 Codex에 주입한다.**

---

## 작업 지시

M1(10건 스모크)이 검수되었다. 이제 AGENTS.md §4.2의 M2를 수행한다.

**범위**: `2026-03-01 ~ 2026-03-31` 전 일자.

M1에서 구현한 `bulk_ingest.py`를 그대로 사용하되, 날짜 범위와 규모가 커졌으므로 다음 사항을 재검증하면서 진행한다:

- 동시성 5 / `throttle()` 0.3초 간격 유지
- 429/503 exponential backoff (최대 5회)
- `FORBIDDEN_HOSTS` 훅 여전히 작동
- sha256 idempotency (재실행 시 전체 skip)

### 실행

```bash
python -m govpress_mcp.bulk_ingest \
  --date-range 2026-03-01..2026-03-31 \
  --data-root /home/$USER/govpress-mcp/data
```

`--date-range` 옵션이 M1에서 구현되지 않았으면 이 시점에 추가한다. CLI 시그니처 변경은 AGENTS.md §4.2 범위 내에서만 허용.

### 집계 및 리포트

`docs/rehearsal-report.md`를 만들고 아래 수치를 모두 포함한다:

```markdown
# M2 리허설 리포트

- 실행 기간: YYYY-MM-DD HH:MM ~ YYYY-MM-DD HH:MM KST
- 범위: 2026-03-01 ~ 2026-03-31 (N 일)
- 전체 대상 건수: M
- 성공 건수: S (S/M = XX.X%)
- skip 분포:
  - hwp_legacy: X건 (X%)
  - no_primary_hwpx: Y건 (Y%)
  - conversion_failed: Z건 (Z%)
- 처리 시간:
  - 중위값: N.N 초/건
  - 95퍼센타일: N.N 초/건
  - 최대: N.N 초/건
- 재시도 통계:
  - 429 발생: N회, 그 중 성공: M회 (M/N = XX.X%)
  - 503 발생: N회, 그 중 성공: M회 (M/N = XX.X%)
- 디스크 사용량 증가:
  - data/raw/2026/03/ — +X.X GB
  - data/md/2026/03/ — +X.X GB
  - 예측 대비: +X%

## 비정상 신호
- (있으면 여기에 나열)
- 없으면 "없음"
```

---

## M2 완료 조건 (전부 ✅ 될 때까지 종료 금지)

AGENTS.md §4.2 그대로.

- [ ] 성공률 ≥95% (HWP 구버전 skip은 성공에서 제외하고 별도 카운트)
- [ ] skip 분포: hwp_legacy <5%, no_primary_hwpx <2%, conversion_failed <1%
- [ ] 중위 처리시간 < 5초/건
- [ ] 429/503 재시도 성공률 ≥99%
- [ ] 디스크 증가가 예측(월 ~2GB) 대비 ±30% 이내
- [ ] `docs/rehearsal-report.md` 작성 완료

---

## M2 완료 보고 형식

표준 출력 마지막 줄:

```
M2 완료. 1개월 리허설 성공. 5년 백필 승인 대기.
```

한 조건이라도 ✗면 M3 절대 착수 금지. 실패 원인 분석을 `docs/rehearsal-report.md`에 함께 기록하고 멈춘다.

---

## 비상 중단 재확인 (AGENTS.md §4.5)

M2는 규모가 크기 때문에 비상 호출 조건이 특히 잘 감지돼야 한다:

- HWP 구버전 비율 10% 초과 → EMERGENCY STOP (도메인 가정 붕괴 신호)
- 429/503이 한 시간 이상 지속 → EMERGENCY STOP (서비스키 rate limit 추정)
- 디스크 사용량 120GB 초과 → EMERGENCY STOP
- `is_zip_container=True`인데 `convert_hwpx` 실패율 5% 초과 → EMERGENCY STOP

**M3는 사람이 "M3 진행" 이라고 지시할 때까지 착수 금지.**
