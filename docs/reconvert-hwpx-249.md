# Reconvert HWPX 249 Analysis

`conversion_failed` HWPX 대상 `249`건의 latest `failed.jsonl` 기준 세부 분류:

| category | count | meaning |
|---|---:|---|
| `hwpx_invalid_token` | `223` | XML 섹션 파싱 중 `not well-formed (invalid token)` |
| `hwpx_syntax_error` | `16` | XML 섹션 파싱 중 `syntax error` |
| `hwpx_invalid_file` | `7` | HWPX 파일 자체가 손상되었거나 유효하지 않음 |
| `hwpx_unpack_error` | `1` | 구조 분해 중 `not enough values to unpack` |
| `hwpx_other` | `2` | 본문 섹션을 찾지 못함 |

## Main Takeaway

핵심은 `249`건 중 `239`건이 XML 파서 계열 실패라는 점이다.

- `invalid_token 223`
- `syntax_error 16`

즉 현재 재변환 보류의 주원인은 입력 원본 재다운로드 문제가 아니라 converter의 HWPX 파싱 경로가
이 파일군을 여전히 처리하지 못한다는 데 있다.

## Invalid File Subgroup (7)

`hwpx_invalid_file 7`건은 다시 두 부류로 나뉜다.

### 1. Non-zip HWPX-like binary (6)

이 6건은 `.hwpx` 확장자지만 zip 기반 Open Packaging 컨테이너가 아니다.

- `156505432`
- `156506554`
- `156563206`
- `156609370`
- `156610213`
- `156688386`

목록 파일:

- `data/fetch-log/reconvert-hwpx-notzip-6.txt`

### 2. Broken zip central directory (1)

- `156577782`

특징:

- `zipfile.is_zipfile()`는 `True`
- 실제 `zipfile.ZipFile()` 오픈 시 `BadZipFile: Bad magic number for central directory`

즉 “zip처럼 보이지만 실제 central directory가 깨진 손상 archive”다.

## Representative IDs

### `hwpx_invalid_token`

- `156747079`
- `156747394`
- `156747531`
- `156742677`
- `156748554`

### `hwpx_syntax_error`

- `156518824`
- `156535770`
- `156542177`
- `156546184`
- `156565586`

### `hwpx_other`

- `156515591` — `본문 섹션을 찾을 수 없습니다`
- `156549309` — `본문 섹션을 찾을 수 없습니다`

## Conclusion

HWPX `249`건은 현재 세 그룹으로 나눠 대응해야 한다.

1. XML parser 개선 대상
   - `239건` (`invalid_token + syntax_error`)
2. 손상/비표준 컨테이너 분기 대상
   - `7건` (`invalid_file`)
3. 문서 구조 탐지 로직 개선 대상
   - `3건` (`unpack_error + other`)

따라서 `reconvert.py` 전량 재실행보다 우선해야 할 일은:

- converter의 HWPX XML 파서 개선
- 비zip/손상 zip HWPX에 대한 별도 처리 분기 설계
