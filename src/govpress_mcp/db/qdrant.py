from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urljoin
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class QdrantCollectionStats:
    points_count: int
    indexed_vectors_count: int
    status: str


@dataclass(frozen=True)
class QdrantSearchHit:
    chunk_id: str
    news_item_id: str
    approve_date: str | None
    department: str | None
    entity_type: str | None
    score: float


class QdrantHTTPClient:
    def __init__(self, base_url: str, collection_name: str = "briefing_chunks") -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.collection_name = collection_name

    def collection_stats(self) -> QdrantCollectionStats:
        payload = self._get_json(f"collections/{self.collection_name}")
        result = payload["result"]
        return QdrantCollectionStats(
            points_count=int(result.get("points_count", 0)),
            indexed_vectors_count=int(result.get("indexed_vectors_count", 0)),
            status=str(result.get("status", "unknown")),
        )

    def search(
        self,
        vector: list[float],
        *,
        limit: int,
        score_threshold: float = 0.5,
    ) -> list[QdrantSearchHit]:
        payload = self._post_json(
            f"collections/{self.collection_name}/points/search",
            {
                "vector": vector,
                "limit": limit,
                "with_payload": True,
                "score_threshold": score_threshold,
            },
        )
        results: list[QdrantSearchHit] = []
        for item in payload.get("result", []):
            point_payload = item.get("payload", {})
            results.append(
                QdrantSearchHit(
                    chunk_id=str(point_payload.get("chunk_id", "")),
                    news_item_id=str(point_payload.get("news_item_id", "")),
                    approve_date=point_payload.get("approve_date"),
                    department=point_payload.get("department"),
                    entity_type=point_payload.get("entity_type"),
                    score=float(item.get("score", 0.0)),
                )
            )
        return results

    def _get_json(self, path: str) -> dict:
        with urlopen(urljoin(self.base_url, path), timeout=10) as response:
            return json.load(response)

    def _post_json(self, path: str, payload: dict) -> dict:
        request = json.dumps(payload).encode("utf-8")
        req = Request(
            urljoin(self.base_url, path),
            data=request,
            headers={"content-type": "application/json"},
        )
        with urlopen(req, timeout=30) as response:
            return json.load(response)
