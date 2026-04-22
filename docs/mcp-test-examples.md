# MCP Test Examples

이 문서는 구현된 Govpress MCP 서버를 빠르게 검증하는 예시 모음이다.

- 공개 엔드포인트: `https://mcp.govpress.cloud/mcp`
- 로컬 엔드포인트: `http://127.0.0.1:8001/mcp`
- 프로토콜: JSON-RPC over HTTP POST

## 기본 확인

### 1. tools/list

```bash
curl -sS https://mcp.govpress.cloud/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }' | jq '.result.tools | length'
```

예상 결과:

```json
8
```

### 2. get_stats

```bash
curl -sS https://mcp.govpress.cloud/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "get_stats",
      "arguments": {}
    }
  }' | jq -r '.result.content[0].text | fromjson | .data'
```

예상 핵심 필드:

- `doc_count: 130012`
- `indexed_docs: 129934`
- `qdrant_points_count: 454125`

## 단건/목록 조회

### 3. get_briefing

```bash
curl -sS https://mcp.govpress.cloud/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "get_briefing",
      "arguments": {
        "id": "156445671",
        "max_chars": 800
      }
    }
  }' | jq -r '.result.content[0].text | fromjson | .data'
```

확인 포인트:

- `id`
- `title`
- `department`
- `source_url`
- `body`

### 4. list_briefings

```bash
curl -sS https://mcp.govpress.cloud/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "id": 4,
    "method": "tools/call",
    "params": {
      "name": "list_briefings",
      "arguments": {
        "department": "통일부",
        "page_size": 3
      }
    }
  }' | jq -r '.result.content[0].text | fromjson | .data'
```

확인 포인트:

- `items`
- `total`
- `page`
- `has_more`

## 검색 도구

### 5. fts_search

```bash
curl -sS https://mcp.govpress.cloud/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "id": 5,
    "method": "tools/call",
    "params": {
      "name": "fts_search",
      "arguments": {
        "query": "탄소중립",
        "limit": 5
      }
    }
  }' | jq -r '.result.content[0].text | fromjson | .data.items'
```

확인 포인트:

- 결과 1건 이상
- `snippet`에 `<mark>...</mark>` 포함

### 6. search_briefing

```bash
curl -sS https://mcp.govpress.cloud/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "id": 6,
    "method": "tools/call",
    "params": {
      "name": "search_briefing",
      "arguments": {
        "query": "탄소중립",
        "limit": 5
      }
    }
  }' | jq -r '.result.content[0].text | fromjson | .data.items'
```

확인 포인트:

- 결과 1건 이상
- 각 항목에 `score`, `title`, `department`, `approve_date`, `source_url`

## 복합 도구

### 7. cross_check_ministries

```bash
curl -sS https://mcp.govpress.cloud/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "id": 7,
    "method": "tools/call",
    "params": {
      "name": "cross_check_ministries",
      "arguments": {
        "topic": "탄소중립",
        "min_ministries": 2
      }
    }
  }' | jq -r '.result.content[0].text | fromjson | .data'
```

확인 포인트:

- `items`에 부처 2개 이상
- 부처별 최고 score 문서 1건씩

### 8. trace_policy

```bash
curl -sS https://mcp.govpress.cloud/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "id": 8,
    "method": "tools/call",
    "params": {
      "name": "trace_policy",
      "arguments": {
        "keyword": "탄소중립"
      }
    }
  }' | jq -r '.result.content[0].text | fromjson | .data.nodes[:5]'
```

확인 포인트:

- 노드 2개 이상
- `approve_date` 오름차순

### 9. compare_versions

```bash
curl -sS https://mcp.govpress.cloud/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "id": 9,
    "method": "tools/call",
    "params": {
      "name": "compare_versions",
      "arguments": {
        "briefing_id": "156445671"
      }
    }
  }' | jq -r '.result.content[0].text | fromjson | .data'
```

예상 결과:

- `experimental: true`
- `note: "checksums_history 누적 후 활성화 예정"`
- `versions: []`

## 로컬 서버 테스트

공개 URL 대신 로컬에서 바로 검증하려면 URL만 바꾸면 된다.

```bash
curl -sS http://127.0.0.1:8001/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }'
```

## 빠른 점검 체크리스트

- `tools/list == 8`
- `get_stats.doc_count == 130012`
- `fts_search("탄소중립")` 결과 1건 이상
- `search_briefing("탄소중립")` 결과 1건 이상
- `cross_check_ministries("탄소중립")` 부처 2개 이상
- `trace_policy("탄소중립")` 노드 2개 이상
- `compare_versions("156445671")` 는 experimental 스텁 응답

