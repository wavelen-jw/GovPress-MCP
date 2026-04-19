# M2 리허설 리포트

- 실행 기간: 2026-04-19 21:43 ~ 2026-04-19 21:43 KST
- 범위: 2026-03-26 ~ 2026-03-26 (1 일)
- 전체 대상 건수: 162
- HWPX 성공 건수: 158 (158/161 = 98.1%)
- skip 분포:
  - hwp_legacy: 0건 (0.0%)
  - pdf_queue: 1건 (0.6%)
  - odt_only/no_attachments: 3건 (1.9%)
  - conversion_failed: 0건 (0.0%)
- 다운로드 실패 유형:
  - hwpx_html_error_page: 1건
  - hwpx_empty_payload: 0건
  - connection_error: 0건
  - 기타: 0건
- 처리 시간:
  - 중위값: 0.0 초/건
  - 95퍼센타일: 0.0 초/건
  - 최대: 0.0 초/건
- 재시도 통계:
  - 429 발생: 0회, 그 중 성공: 0회 (100.0%)
  - 503 발생: 0회, 그 중 성공: 0회 (100.0%)
## 기준 조정 사유
- 2026-04-18 리허설 실측에서 no_primary_hwpx가 실제 소스 분포를 반영하는 항목으로 확인되어, M3부터는 pdf_queue로 분리해 성공률 모수에서 제외한다.
- frontmatter는 v2(govpress_version, govpress_commit, source_format)로 통일하고 기존 산출물은 stamp_version.py로 백필했다.

## 비정상 신호
- 없음
