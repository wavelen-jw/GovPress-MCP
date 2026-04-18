# M4 작업 프롬프트 — PDF 백필 트랙

**이 프롬프트는 M3 완료 + 사람 승인 후에만 Codex에 주입한다.**

M3에서 HWPX를 처리하는 동안 PDF만 있는 보도자료는 `data/fetch-log/pdf-queue.jsonl`에 쌓였다. M4는 이 큐를 소진해서 MD를 생성하는 별도 트랙이다.

---

## 선행 확인 (M4 착수 전 반드시 점검)

```bash
# pdf-queue.jsonl 건수 확인
wc -l data/fetch-log/pdf-queue.jsonl

# Java 11+ 설치 여부 (convert_pdf 필요)
java -version 2>&1 | head -1

# govpress_converter.convert_pdf 가용 확인
python3 -c "import govpress_converter; govpress_converter.convert_pdf.__doc__"
# RuntimeError가 나지 않고 docstring이 출력되면 OK
```

Java 11+ 미설치 시: `sudo apt-get install -y openjdk-11-jdk` 후 재확인.

---

## 작업 지시

### 4.1 PDF 백필 실행

`data/fetch-log/pdf-queue.jsonl`을 입력으로 받아 PDF를 다운로드·변환한다.

**처리 흐름 (item별)**:

1. `pdf-queue.jsonl`에서 `news_item_id` + `approve_date` 읽기
2. `checksums.db`에서 해당 `news_item_id` 조회 → 이미 `source_format IN ('hwpx','pdf')`로 기록됐으면 skip (idempotent)
3. `client.list_items(approve_date)` 재호출 → 해당 `news_item_id`의 item 찾기
4. `item.primary_pdf`가 없으면 `pdf_unavailable`로 failed.jsonl 기록 후 skip
5. PDF 다운로드 → 비정상 응답(HTML 에러 페이지, 0 byte) → `pdf_html_error_page` / `pdf_empty_payload`로 failed.jsonl 기록 후 skip
6. `data/raw/{yyyy}/{mm}/{news_item_id}.pdf` 저장 + sha256 계산
7. `govpress_converter.convert_pdf(path, timeout=300)` → MD 텍스트
8. frontmatter v2 생성 (`source_format: pdf`):
   ```yaml
   ---
   id: <news_item_id>
   title: <item.title>
   department: <item.department>
   approve_date: <ISO 8601>
   entity_type: central | metro | local
   original_url: <item.original_url>
   sha256: <PDF의 sha256>
   revision: 1
   govpress_version: <govpress-converter 버전>
   govpress_commit: <gov-md-converter git SHA>
   source_format: pdf
   raw_path: data/raw/yyyy/mm/{news_item_id}.pdf
   ---
   ```
9. `data/md/{yyyy}/{mm}/{news_item_id}.md` 저장
10. `checksums.db` UPDATE (`govpress_version`, `govpress_commit`, `source_format='pdf'`, `fetched_at`)

**실행 명령 예시** (신규 CLI `--pdf-queue` 옵션 또는 별도 스크립트):

```bash
nohup python -m govpress_mcp.bulk_ingest_pdf \
  --pdf-queue data/fetch-log/pdf-queue.jsonl \
  --data-root /home/$USER/govpress-mcp/data \
  --log-json data/fetch-log/pdf-backfill.jsonl \
  > logs/pdf-backfill.stdout 2>&1 &
```

`bulk_ingest_pdf.py`를 새로 만들거나, 기존 `bulk_ingest.py`에 `--pdf-queue` 옵션을 추가하는 방식 모두 가능. 단, HWPX 트랙과 코드가 분리돼야 실패 원인 디버깅이 쉽다. 어느 구조를 택하든 PDF 전용 실패 사유(`pdf_html_error_page` 등)가 명확히 구분되어야 한다.

### 4.2 Rate Limit (AGENTS.md §1.9 그대로 적용)

- 동시성 5 / 0.3초 간격
- 429/503 exponential backoff (최대 5회)
- sha256 idempotency: 중간 실패 후 재시작해도 이미 완료된 건 skip

### 4.3 convert_pdf 성능 주의사항

- `convert_pdf`는 Java 프로세스를 spawn하므로 HWPX보다 느리다. **동시성 3 이하**로 낮추는 것을 권장 (Java 힙 경합 방지). `asyncio.Semaphore(3)` 사용.
- `timeout=300` 기본값 유지. 초과 시 `pdf_timeout`으로 failed.jsonl 기록.
- GPU는 PDF 변환에 사용되지 않는다.

### 4.4 M4 완료 조건

- [ ] `pdf-queue.jsonl` 전체 건 처리 완료 (성공 + skip + 실패 합산이 큐 건수와 일치)
- [ ] HWPX 성공률 기준과 별도로 **PDF 성공률 ≥80%** (PDF는 소스 품질 편차가 커서 기준 완화)
- [ ] `conversion_failed`(PDF 변환 실패) <5%
- [ ] `docs/m4-report.md` 작성 완료

`docs/m4-report.md` 필수 항목:

```markdown
# M4 PDF 백필 리포트

- 실행 기간: YYYY-MM-DD ~ YYYY-MM-DD
- pdf-queue 입력 건수: N
- PDF 성공: S건 (S/N = XX.X%)
- skip 분포:
  - pdf_unavailable: X건 (API 재조회 시 PDF 없음)
  - pdf_html_error_page: Y건
  - pdf_empty_payload: Z건
  - pdf_timeout: W건
  - 기타: V건
- 성공한 MD 중 source_format=pdf 건수: S건
- checksums.db NULL(govpress_version) 잔재: 0건이어야 함
```

---

## M4 완료 보고 형식

표준 출력 마지막 줄:

```
M4 완료. PDF 백필 종료. 사람 확인 대기.
```

M4 완료 후 Codex는 멈추고 사람에게 반환한다. Phase 1 전체 완료(HWPX M3 + PDF M4). Phase 2(색인)는 Claude 세션에서 별도 설계.

---

## 비상 중단 (AGENTS.md §4.5 + PDF 추가 조건)

- `api2.govpress.cloud` 호출 감지 → EMERGENCY STOP
- 서비스키 노출 → EMERGENCY STOP
- 429/503 1시간 이상 지속 → EMERGENCY STOP
- 디스크 사용량 120GB 초과 → EMERGENCY STOP
- `convert_pdf` 실패율 **10% 초과** (누적, PDF 품질 편차 감안해 HWPX 기준 5%보다 완화) → EMERGENCY STOP
- Java OOM·ClassNotFoundException 연속 5회 → EMERGENCY STOP (JVM 환경 문제)

비상 호출 보고 형식은 AGENTS.md §4.5 참조.
