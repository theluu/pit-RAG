import json
import statistics
import time
from pathlib import Path

from apps.api.models import QueryRequest


def load_cases(path: str | Path) -> list[dict]:
    with Path(path).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def benchmark(cases: list[dict], execute, pipeline: str = "L7") -> dict:
    rows = []
    for case in cases:
        started = time.perf_counter()
        response = execute(QueryRequest(
            question=case["question"], applicable_date=case["applicable_date"],
            domain=case.get("domain"), pipeline_level=pipeline,
        ))
        expected = set(case.get("expected_document_numbers", []))
        cited = {citation.document_number for citation in response.citations}
        intersection = expected & cited
        rows.append({
            "id": case["id"],
            "citation_precision": len(intersection) / len(cited) if cited else float(not expected),
            "citation_recall": len(intersection) / len(expected) if expected else float(not cited),
            "abstained": not response.citations,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        })
    latencies = sorted(row["latency_ms"] for row in rows)
    p95_index = max(0, round(0.95 * len(latencies)) - 1)
    return {
        "pipeline": pipeline,
        "cases": len(rows),
        "citation_precision": round(statistics.mean(r["citation_precision"] for r in rows), 4),
        "citation_recall": round(statistics.mean(r["citation_recall"] for r in rows), 4),
        "latency_p50_ms": round(statistics.median(latencies), 2),
        "latency_p95_ms": latencies[p95_index],
        "results": rows,
    }
