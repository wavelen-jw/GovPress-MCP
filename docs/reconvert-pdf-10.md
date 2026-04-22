# Reconvert PDF 10 Analysis

`conversion_failed` PDF 대상 10건의 실제 파일 식별 결과:

| news_item_id | target_date | raw_path | detected_type | interpretation |
|---|---|---|---|---|
| `156463278` | `2021-07-26` | `data/raw/2021/07/156463278.pdf` | `HTML document, ISO-8859 text` | PDF가 아니라 HTML 오류/대체 페이지 |
| `156470767` | `2021-09-13` | `data/raw/2021/09/156470767.pdf` | `data` | `DOCUMENTSAFER_*` 헤더의 비표준 바이너리 |
| `156478475` | `2021-11-02` | `data/raw/2021/11/156478475.pdf` | `Hancom HWP file, version 5.0` | `.pdf` 확장자지만 실제 HWP |
| `156479420` | `2021-11-08` | `data/raw/2021/11/156479420.pdf` | `HTML document, ISO-8859 text` | PDF가 아니라 HTML 오류/대체 페이지 |
| `156488343` | `2021-12-24` | `data/raw/2021/12/156488343.pdf` | `HTML document, ISO-8859 text` | PDF가 아니라 HTML 오류/대체 페이지 |
| `156526033` | `2022-09-16` | `data/raw/2022/09/156526033.pdf` | `data` | `DOCUMENTSAFER_*` 헤더의 비표준 바이너리 |
| `156528290` | `2022-09-29` | `data/raw/2022/09/156528290.pdf` | `data` | `DOCUMENTSAFER_*` 헤더의 비표준 바이너리 |
| `156536255` | `2022-11-14` | `data/raw/2022/11/156536255.pdf` | `data` | `DOCUMENTSAFER_*` 헤더의 비표준 바이너리 |
| `156734032` | `2025-10-23` | `data/raw/2025/10/156734032.pdf` | `Hancom HWP file, HWPX` | `.pdf` 확장자지만 실제 HWPX |
| `156744745` | `2026-02-13` | `data/raw/2026/02/156744745.pdf` | `PDF document, version 1.4, 77 page(s)` | 정상 PDF |

## Conclusion

- 정상 PDF: `1`
- HTML 문서: `3`
- HWP/HWPX로 위장된 `.pdf`: `2`
- `DOCUMENTSAFER_*` 비표준 바이너리: `4`

`156744745`는 외형상 정상 PDF(`PDF 1.4, 77 pages`)지만, CLI 직접 실행 결과도 실패했다.

- veraPDF parser error:
  - `VeraPDFParserException: Error while parsing object : 61 0`
  - root cause:
    - `invalid pdf dictionary(object key = 61 0 obj, offset = 1573364)`

즉 PDF `10`건 중 실제로 `convert_pdf()` 재시도 대상으로 볼 수 있는 정상 PDF는 `1건`처럼 보였지만,
그 1건조차 내부 구조 손상으로 현재 변환기 체인에서는 처리되지 않는다.

결론적으로 PDF `10`건은 현 시점에서 `reconvert.py` 전량 재실행 대상이 아니다.
