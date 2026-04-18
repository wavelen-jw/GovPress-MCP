# M3 작업 프롬프트 — 5년 백필 + 일일 증분 systemd timer

**이 프롬프트는 M2 완료 + 사람 승인 후에만 Codex에 주입한다.**

---

## 작업 지시

M1(스모크) · M2(1개월 리허설) 모두 통과했다. 이제 AGENTS.md §4.3의 M3를 수행한다.

### 3.1 5년 백필 실행

**범위**: `2021-04-18 ~ 2026-04-18` 전 일자. 약 1800일 × 일평균 100~200건 = **누적 20~40만 건** 예상. 실행 일정 2~4주.

```bash
nohup python -m govpress_mcp.bulk_ingest \
  --date-range 2021-04-18..2026-04-18 \
  --data-root /home/$USER/govpress-mcp/data \
  --log-json data/fetch-log/backfill.jsonl \
  > logs/backfill.stdout 2>&1 &
```

다음 사항을 유지하며 진행:

- 동시성 5 / `throttle()` 0.3초 간격
- 429/503 exponential backoff (최대 5회)
- sha256 idempotency — 중간에 죽어도 재시작 안전
- 진행 상황을 `data/fetch-log/backfill.jsonl` 에 건별 append (날짜별 집계는 이 파일을 reduce해서 구함)
- 매일 KST 정각에 `docs/backfill-progress-YYYY-MM-DD.md` 스냅샷 자동 생성 (24시간 내 건수·실패율 요약)

### 3.2 일일 증분 systemd timer 등록

백필과 병행해서 등록해도 되지만, 백필이 일일 증분의 대상 기간과 겹치면 충돌이 난다. 따라서 **백필이 2026-04-17까지 도달한 뒤**에 systemd timer를 활성화한다.

`/etc/systemd/user/govpress-mcp-daily.service`:
```ini
[Unit]
Description=govpress-mcp daily incremental crawl

[Service]
Type=oneshot
WorkingDirectory=%h/projects/govpress-mcp
EnvironmentFile=%h/projects/govpress-mcp/.env
ExecStart=/usr/bin/env python -m govpress_mcp.bulk_ingest --date $(date +%%Y-%%m-%%d) --data-root %h/govpress-mcp/data
```

`/etc/systemd/user/govpress-mcp-daily.timer`:
```ini
[Unit]
Description=govpress-mcp daily incremental crawl timer

[Timer]
OnCalendar=*-*-* 06:00:00 Asia/Seoul
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now govpress-mcp-daily.timer
systemctl --user list-timers | grep govpress-mcp
```

7일 연속 정상 동작 확인 (`journalctl --user -u govpress-mcp-daily.service --since "7 days ago"` 실패 0회).

### 3.3 Phase 1 최종 리포트

`docs/phase1-report.md` 작성:

```markdown
# Phase 1 완료 보고

## 실행 요약
- 백필 기간: YYYY-MM-DD ~ YYYY-MM-DD (실행 N일)
- 대상 기간: 2021-04-18 ~ 2026-04-18
- 전체 대상 건수: M
- 성공 건수: S (S/M = XX.X%)

## skip 분포
| 사유 | 건수 | 비율 |
|---|---:|---:|
| hwp_legacy | X | X% |
| no_primary_hwpx | Y | Y% |
| conversion_failed | Z | Z% |

## 기관별 MD 개수 vs korea.kr 공식 목록
| 기관 | 공식 | 생성 | diff | diff% |
|---|---:|---:|---:|---:|
| (중앙 22개 + 광역 17개 + 기초 N개) | | | | |

전체 diff: ±X%  (목표: ±5% 이내)

## 처리 성능
- 중위 처리시간: N.N 초/건
- 평균 처리량: N 건/시간

## 일일 증분 상태
- systemd timer 등록: 2026-XX-XX
- 7일 연속 정상 동작 여부: YES/NO
- 실패 일자: (있으면 나열)

## LICENSE-data 파일
- 위치: 레포 루트 `LICENSE-data`
- 공공누리 1유형 전문 포함: YES
- 데이터 소스 구조 설명 포함: YES

## 누락·재시도 실패 건
- 파일: data/fetch-log/failed.jsonl
- 건수: N
- 주요 사유: (분포)
```

### 3.4 LICENSE-data 파일 생성

리포 루트에 `LICENSE-data` 파일 생성 (공공누리 1유형 전문 + 데이터 소스 구조 + 제3자 재사용 안내). 템플릿은 https://www.kogl.or.kr/info/license.do 제1유형 참고.

frontmatter의 `license` 필드나 MCP footer는 추가하지 말 것 — 고지는 이 한 파일로만.

---

## M3 완료 조건 (전부 ✅ 될 때까지 종료 금지)

AGENTS.md §4.3 그대로.

- [ ] 5년 백필 전량 완료
- [ ] MD 개수가 korea.kr 공식 기관별 목록과 ±5% 이내
- [ ] systemd timer 등록 + 7일 연속 일일 증분 정상 동작
- [ ] `docs/phase1-report.md` 작성 완료
- [ ] 리포 루트 `LICENSE-data` 파일 생성 완료

---

## M3 완료 보고 형식

표준 출력 마지막 줄:

```
M3 완료. Phase 1 종료. 사람 확인 대기.
```

M3 완료 = **진짜 Phase 1 종료**. Codex는 여기서 멈추고 사람에게 반환한다. Phase 2(색인·derive_hot.py·Qdrant)는 Claude 세션에서 설계한 뒤 별도 프롬프트로 재진입.

---

## 비상 중단 재확인 (AGENTS.md §4.5)

5년 백필은 최장 실행이라 비상 호출 조건을 특히 잘 지켜야 한다:

- `api2.govpress.cloud` 호출 감지 → 즉시 EMERGENCY STOP
- 서비스키 노출 감지 → 즉시 EMERGENCY STOP
- HWP 구버전 비율 10% 초과 (전체 누적 기준) → EMERGENCY STOP
- 429/503 1시간 이상 지속 → EMERGENCY STOP
- 디스크 사용량 120GB 초과 → EMERGENCY STOP
- `convert_hwpx` 실패율 5% 초과 (누적) → EMERGENCY STOP

비상 호출 보고 형식은 AGENTS.md §4.5 참조. 자동 복구 시도 금지.
