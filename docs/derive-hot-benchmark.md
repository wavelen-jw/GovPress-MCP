# Derive Hot Benchmark

작성: 2026-04-21

## 목적

`derive_hot.py`의 색인 성능을 GPU TEI와 CPU TEI에서 비교한다.

비교 기준:
- 동일 코드 경로 (`python -m govpress_mcp.derive_hot`)
- 동일 모델 (`BAAI/bge-m3`)
- 동일 청킹 로직
- Qdrant upsert 포함 wall-clock 기준

## 환경

- GPU TEI: `ghcr.io/huggingface/text-embeddings-inference:latest`
- GPU: `NVIDIA GeForce RTX 3080`
- GPU TEI 포트: `http://localhost:18080`
- CPU TEI: `ghcr.io/huggingface/text-embeddings-inference:cpu-latest`
- CPU TEI 포트: `http://localhost:18081`
- 벤치용 Qdrant: `http://localhost:16333`

## GPU 실측

전량 색인 실행 중간 시점 스냅샷:

- 경과 시간: `255초`
- Qdrant 적재 청크: `12,079`
- 속도:
  - `47.4 chunks/sec`
  - `2,842 chunks/min`

샘플 100건 기준 평균 청크 수:

- `4.5 chunks/doc`

이를 문서 기준으로 환산하면:

- `약 10.5 docs/sec`
- `약 632 docs/min`

## CPU 실측

CPU TEI + 벤치용 Qdrant에 대해 `--sample 100`으로 측정했다.

실행 명령:

```bash
PYTHONPATH=src .venv/bin/python -m govpress_mcp.derive_hot \
  --sample 100 \
  --data-root /home/wavel/projects/govpress-mcp/data \
  --qdrant-url http://localhost:16333 \
  --tei-url http://localhost:18081 \
  --db /tmp/govpress-bench-cpu.db \
  --checkpoint 50
```

중간 종료 시점 실측:

- 경과 시간: `275초`
- Qdrant 적재 청크: `93`
- 속도:
  - `0.338 chunks/sec`
  - `20.3 chunks/min`

문서 기준 환산:

- `약 0.075 docs/sec`
- `약 4.5 docs/min`

참고:

- CPU 벤치는 성능 차이가 충분히 확인된 시점에서 중단했다.
- 중단 시점까지 CPU TEI는 `2169%` CPU, `14.45 GiB` 메모리를 사용했다.

## 비교

| 항목 | GPU | CPU |
|---|---:|---:|
| chunks/sec | `47.4` | `0.338` |
| chunks/min | `2,842` | `20.3` |
| docs/min (평균 4.5 chunks/doc 환산) | `632` | `4.5` |
| 상대 속도 | `1.0x` | `약 0.007x` |

즉 현재 실측 기준으로 GPU 색인은 CPU보다 대략 `140배` 빠르다.

## 결론

- `derive_hot.py` 전량 색인은 CPU로 돌릴 실익이 없다.
- Hot 색인 전량 구축은 RTX 3080 GPU TEI 유지가 맞다.
- CPU TEI는 기능 검증 또는 매우 소규모 샘플 테스트 용도로만 적합하다.
