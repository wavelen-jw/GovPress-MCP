# M2 리허설 리포트

- 실행 기간: 2026-04-22 03:00 ~ 2026-04-22 03:01 KST
- 범위: 2026-04-21 ~ 2026-04-21 (1 일)
- 전체 대상 건수: 135
- HWPX 성공 건수: 111 (111/116 = 95.7%)
- skip 분포:
  - hwp_legacy: 5건 (3.7%)
  - pdf_queue: 0건 (0.0%)
  - odt_only/no_attachments: 5건 (3.7%)
  - conversion_failed: 0건 (0.0%)
- 다운로드 실패 유형:
  - hwpx_html_error_page: 0건
  - hwpx_empty_payload: 0건
  - connection_error: 0건
  - 기타: 0건
- 처리 시간:
  - 중위값: 0.3 초/건
  - 95퍼센타일: 0.5 초/건
  - 최대: 2.2 초/건
- 재시도 통계:
  - 429 발생: 0회, 그 중 성공: 0회 (100.0%)
  - 503 발생: 0회, 그 중 성공: 0회 (100.0%)
## 기준 조정 사유
- 2026-04-18 리허설 실측에서 no_primary_hwpx가 실제 소스 분포를 반영하는 항목으로 확인되어, M3부터는 pdf_queue로 분리해 성공률 모수에서 제외한다.
- frontmatter는 v2(govpress_version, govpress_commit, source_format)로 통일하고 기존 산출물은 stamp_version.py로 백필했다.

## 비정상 신호
- 없음
