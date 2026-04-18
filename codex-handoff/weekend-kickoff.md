# 이번 주말 착수 체크리스트 (사람용)

2026-04-18 ~ 04-19. 서버W WSL에서 Codex CLI로 Phase 1 돌린다.

---

## 금요일 밤 (준비, 15분)

1. 서버W WSL 접속
   ```bash
   wsl -d Ubuntu-24.04
   cd ~/projects
   ```
2. 서비스키 확인 (이미 보유 중인 값)
   ```bash
   echo $GOVPRESS_POLICY_BRIEFING_SERVICE_KEY | head -c 8 ; echo
   ```
   비어 있으면 Govpress `.env`에서 복사
3. Codex CLI 설치 확인
   ```bash
   codex --version
   ```
4. 디스크 여유 확인 (최소 150GB 권장)
   ```bash
   df -h ~/
   ```

## 토요일 오전 — M1 (핸드오프 복사 + 스모크 10건, 1~2시간)

5. 프로젝트 초기화 (00-시작하기.md §2)
6. `.env`에 서비스키 저장 + `.gitignore` 구성 (00-시작하기.md §3.1)
7. `codex` 실행 후 00-시작하기.md §3.2의 초기 지시 블록 붙여넣기
8. Codex가 `M1 완료. 10건 스모크 성공. 승인 대기.` 로 멈춘 뒤 00-시작하기.md §4.1 검수 절차
9. 문제 없으면 Codex 창에 **"M2 진행"** 입력 후 `prompts/bulk_ingest_phase1_m2.md` 내용 붙여넣기

## 토요일 오후~일 오전 — M2 (1개월 리허설, 3~6시간)

10. Codex가 M2 프롬프트대로 2026-03-01 ~ 2026-03-31 전체를 처리
11. Codex가 `M2 완료. 1개월 리허설 성공. 5년 백필 승인 대기.` 로 멈춘 뒤 00-시작하기.md §4.2 검수 절차
12. 성공률 ≥95%·HWP <5%·처리시간 <5초/건 만족하면 Codex 창에 **"M3 진행"** 입력 후 `prompts/bulk_ingest_phase1_m3.md` 내용 붙여넣기

## 일요일~평일 — M3 (5년 백필 + systemd timer, 2~4주)

13. Codex가 M3 프롬프트대로 2021-04-18 ~ 2026-04-18 백필 시작
14. 백필은 오래 걸리므로 `nohup`으로 띄워두고 매일 아침 `docs/backfill-progress-YYYY-MM-DD.md` 확인
15. 백필이 2026-04-17까지 도달하면 Codex가 자동으로 systemd timer 등록 단계로 넘어감
16. 7일 연속 일일 증분 정상 동작 확인 후 Codex가 `M3 완료. Phase 1 종료.` 보고
17. 00-시작하기.md §4.3 최종 검수 → Claude 세션으로 돌아와 Phase 2 설계 착수

---

## 실행 중 사람이 결정해야 하는 순간

Codex가 AGENTS.md §4.5의 **EMERGENCY STOP** 을 외치거나, 아래 신호가 보이면 Claude 세션으로 돌아와 대응 지시를 받는다.

| 상황 | 감지 지점 | 대응 |
|---|---|---|
| HWP 비율이 10% 이상 | M2 리허설 리포트 | Claude에 돌아와 Phase 1a에 LibreOffice 변환 추가 재협상 |
| korea.kr 429가 한 시간 이상 지속 | M2·M3 실행 중 | bulk 전용 서비스키 분리 재검토 (라운드 5에서 "현상 유지"로 결정했지만 징후 감지 시 재오픈) |
| 특정 기관의 첨부가 404 반복 | M2·M3 실행 중 | 그 기관만 log-and-continue, 전체 파이프라인은 계속 |
| 디스크 사용량 120GB 초과 | M3 백필 중 | LFS 한도 정책 발동 검토, Codex에 중단 지시 |
| MD 개수가 공식 목록 대비 ±10% 이상 차이 | M3 phase1-report.md | Phase 2 진입 보류, 누락 원인 조사 |
| 서비스키 노출 | 어느 단계든 | **즉시** 키 rotation + `git filter-repo`로 커밋 히스토리 제거 |

---

## 결정 이력 확인용 (혼동 시 참조)

- 전체 확정 결정: `../데이터-저장-아키텍처.md` §10 (15개 항목)
- Codex 불변 조건: `AGENTS.md` §1, §4, §5
- MCP 도구 명세(Phase 2): `../Govpress-MCP-구현명세.md`
- 논의 이력 요약: 메모리 `project_govpress_mcp_decisions.md`

---

## Phase 2에서 결정할 항목 (지금 결정하지 말 것)

- Qdrant 버전 고정 (컬렉션 migration 리스크 방지)
- BGE-M3 TEI 컨테이너 버전 + torch 호환성 매트릭스
- Redis 핫셋 500건 LRU 초기 seed (어떤 기준으로 top-500?)
- FTS5 한국어 토크나이저 최종 선택 (trigram vs mecab-ko 실험 후)
- MCP 8개 도구 각각의 SQL·벡터·하이브리드 쿼리 템플릿
- `docs/weekly-ops-report.md` 자동 생성 스크립트
- ministry_alias 초기 버전 (중앙 22 + 광역 17)
- GitHub public 전환 여부 (Phase 2 색인 검증 후)

이들은 Phase 1 끝날 때쯤 재오픈.
