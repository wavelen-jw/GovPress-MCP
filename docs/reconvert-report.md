# Reconvert Report

## Summary

- 목적: converter 업그레이드 이후 `conversion_failed` 항목 재변환 검증
- 대상 문서ID: `259`
  - `hwpx`: `249`
  - `pdf`: `10`
- 구현 파일: `src/govpress_mcp/reconvert.py`
- 상태: **샘플 검증 후 전량 실행 보류**

## Sample Validation

실행 명령:

```bash
export JAVA_HOME=/home/wavel/.local/opt/jdk-11.0.25+9
export PATH="/home/wavel/projects/govpress-mcp/.venv/bin:$JAVA_HOME/bin:$PATH"
cd /home/wavel/projects/govpress-mcp
set -a && source .env
PYTHONPATH=src .venv/bin/python -m govpress_mcp.reconvert \
  --data-root /home/wavel/projects/govpress-mcp/data \
  --dry-run --sample 10 --diff \
  --log-json data/fetch-log/reconvert-sample10.jsonl
```

결과:

- 샘플 처리: `10`
- 성공: `0`
- 실패: `10`
- 회귀 가드 skip: `0`
- metadata 누락: `0`
- raw 누락: `0`

샘플 분포:

- `pdf`: `5/5` 실패
- `hwpx`: `5/5` 실패

대표 실패:

- PDF:
  - `ConversionError: PDF 변환에 실패했습니다.`
  - `opendataloader-pdf` CLI가 해당 PDF 원본에서 `exit status 1` 반환
- HWPX:
  - `HWPX 섹션 XML 파싱 실패: not well-formed (invalid token)`
  - `ValueError: not enough values to unpack (expected 2, got 1)`

샘플 ID:

- PDF
  - `156463278`
  - `156470767`
  - `156478475`
  - `156479420`
  - `156488343`
- HWPX
  - `156468376`
  - `156493776`
  - `156494170`
  - `156496683`
  - `156497767`

## Decision

샘플 `0/10`이므로 전량 write 실행은 진행하지 않았다.

이 상태에서 전량 실행을 강행하면:

- `249`건 HWPX는 기존과 같은 파싱 실패를 다시 재생산할 가능성이 높고
- `10`건 PDF는 현재 `opendataloader-pdf` 경로에서 동일한 CLI 실패를 반복할 가능성이 높다

따라서 task #32는 현재 시점에서:

- `reconvert.py` 구현: 완료
- 샘플 dry-run 검증: 완료
- 전량 재변환: **보류**

## Full Target Breakdown

전체 `259`건의 현재 실패 이유를 latest `failed.jsonl` 기준으로 다시 묶으면:

- `hwpx_invalid_token`: `223`
- `hwpx_syntax_error`: `16`
- `hwpx_invalid_file`: `7`
- `hwpx_unpack_error`: `1`
- `pdf_cli_failure`: `10`
- 기타: `2`

로그 기원:

- `unified-collect.jsonl`: `245`
- `unified-retry.jsonl`: `3`
- `m4-reprocess.jsonl`: `1`
- `m5-reprocess.jsonl`: `10`

해석:

- HWPX `249`건은 대부분 여전히 XML 파서 계열 실패다.
- PDF `10`건은 재변환 경로 자체가 아니라 `opendataloader-pdf` CLI 단계에서 막히고 있다.
- 외형상 정상 PDF `1건` (`156744745`)도 veraPDF 파서 오류로 실패한다.

## Raw File Inspection

PDF `10`건의 실제 파일 타입을 확인한 결과:

- 진짜 PDF: `1`
  - `156744745` (`PDF document, version 1.4`)
- HTML 문서: `3`
  - `156463278`
  - `156479420`
  - `156488343`
- Hancom HWP/HWPX로 위장된 `.pdf`: `2`
  - `156478475`
  - `156734032`
- `DOCUMENTSAFER_*` 헤더의 비표준 바이너리: `4`
  - `156470767`
  - `156526033`
  - `156528290`
  - `156536255`

즉 PDF 실패 `10`건 중 실제로 변환기 대상으로 볼 수 있는 “정상 PDF”는 `1건`뿐이다.

또한 HWPX `249`건 중 `6건`은 zip 기반 컨테이너가 아니었다.
파일 식별 결과는 모두 `Hancom HWP (Hangul Word Processor) file, HWPX`로 표시되며 대상은 아래와 같다.

- `156505432`
- `156506554`
- `156563206`
- `156609370`
- `156610213`
- `156688386`

이 6건은 기존 `convert_hwpx()` 경로가 기대하는 zip 컨테이너형 HWPX가 아니므로, 파서 개선 또는 별도 처리 분기가 필요하다.

## Artifacts

- 샘플 로그: `data/fetch-log/reconvert-sample10.jsonl`
- 샘플 실패 로그: `data/fetch-log/reconvert-failed.jsonl`
- 구현 코드: `src/govpress_mcp/reconvert.py`
- PDF 10건 분석: `docs/reconvert-pdf-10.md`
- HWPX 249건 분석: `docs/reconvert-hwpx-249.md`
- 비표준 HWPX 6건 목록: `data/fetch-log/reconvert-hwpx-notzip-6.txt`

## Next Steps

- HWPX `249`건:
  - converter XML 파서 회귀/한계 개선 후 재검증 필요
- PDF `10`건:
  - `opendataloader-pdf` CLI 실패 원인 별도 분석 필요
- 위 두 축 중 하나라도 개선된 뒤 다시:

```bash
PYTHONPATH=src .venv/bin/python -m govpress_mcp.reconvert \
  --data-root /home/wavel/projects/govpress-mcp/data \
  --dry-run --sample 10 --diff
```

에서 성공 샘플이 확인된 뒤 전량 실행으로 넘어가는 것이 안전하다.
