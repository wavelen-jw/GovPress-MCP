# 정책브리핑 API와 Govpress MCP의 차이

이 문서는 공공데이터포털 정책브리핑 API가 실제로 제공하는 기능과, Govpress MCP가 그 위에 어떤 추가 레이어를 얹고 있는지 정리한다.

## 정책브리핑 API가 실제로 주는 것

현재 `PolicyBriefingClient`가 직접 사용하는 정책브리핑 API 기능은 다음 범위다.

- 날짜 범위별 보도자료 목록 조회
  - `startDate=YYYYMMDD`
  - `endDate=YYYYMMDD`
- 문서 기본 메타
  - `NewsItemId`
  - `Title`
  - `MinisterCode`
  - `ApproveDate`
  - `OriginalUrl`
- 첨부파일 목록
  - 파일명
  - 파일 URL

즉 API는 기본적으로 “그 날짜에 나온 문서 목록과 첨부파일 위치”를 주는 서비스다.

## 정책브리핑 API가 직접 주지 않는 것

정책브리핑 API는 다음 기능을 직접 제공하지 않는다.

- 본문 전문 검색
- 의미 검색
- 부처별 입장 비교
- 정책 흐름 시계열 추적
- 변환된 Markdown 본문 조회
- 색인 통계
- 버전 비교

이 기능들은 Govpress가 수집한 원본을 Markdown으로 변환하고, 별도 색인 레이어를 구축했기 때문에 가능한 것이다.

## Govpress MCP가 추가하는 레이어

Govpress MCP는 정책브리핑 API 위에 다음 단계를 더한다.

1. 첨부파일 다운로드
2. HWPX/PDF → Markdown 변환
3. `data/md/` corpus 저장
4. SQLite FTS5 본문 색인
5. BGE-M3 임베딩 + Qdrant 의미 검색
6. 비교·추적용 도구 제공

그래서 Govpress MCP는 단순 API 프록시가 아니라, **변환 + 저장 + 색인 + 검색**이 결합된 읽기 전용 서비스다.

## 현재 MCP 도구 중 API 래핑만으로 가능한 것

### 바로 가능

- `list_briefings`
  - 날짜별 목록과 기본 메타를 API가 직접 제공하므로, 여러 날짜를 순회하는 서버 래퍼만 있으면 구현 가능하다.

### 부분 가능

- `get_briefing`
  - 현재 공개 도구는 Markdown 본문을 돌려준다.
  - 정책브리핑 API는 Markdown 본문을 직접 제공하지 않으므로, **현재 형태 그대로는 API 직래핑만으로 구현할 수 없다.**
  - 다만 “단건 메타 조회 + 첨부파일 안내” 수준의 `get_briefing-lite` 형태라면 가능하다.

## 현재 MCP 도구 중 색인/RAG 레이어가 필요한 것

- `fts_search`
  - Markdown 본문과 FTS5 색인이 있어야 한다.
- `search_briefing`
  - TEI 임베딩과 Qdrant가 필요하다.
- `cross_check_ministries`
  - 의미 검색 결과를 부처별로 그룹화한다.
- `trace_policy`
  - 의미 검색 결과를 날짜순으로 정렬해 흐름을 만든다.
- `get_stats`
  - corpus·Qdrant·FTS5 통계를 보여주므로 API 직래핑으로는 불가능하다.

## 결론

정책브리핑 API만으로도 “실시간 목록 조회 서비스”는 만들 수 있다.  
하지만 지금의 Govpress MCP처럼 검색·비교·정책 흐름 추적을 제공하려면, 다음 레이어가 반드시 필요하다.

- Markdown corpus
- SQLite FTS5
- BGE-M3 임베딩
- Qdrant 벡터 색인

요약하면:

- **API 직래핑에 적합한 기능**: `list_briefings`, 축소형 `get_briefing`
- **Govpress 고유 기능**: `fts_search`, `search_briefing`, `cross_check_ministries`, `trace_policy`, `get_stats`
