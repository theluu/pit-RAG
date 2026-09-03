import math


def retrieval_metrics(retrieved: list[str], expected: list[str], k: int = 10) -> dict[str, float]:
    top = retrieved[:k]
    relevant = set(expected)
    hits = [1 if item in relevant else 0 for item in top]
    recall = len(set(top) & relevant) / len(relevant) if relevant else 1.0
    reciprocal_rank = next((1 / (i + 1) for i, hit in enumerate(hits) if hit), 0)
    dcg = sum(hit / math.log2(i + 2) for i, hit in enumerate(hits))
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    return {
        f"recall@{k}": round(recall, 4),
        "mrr": round(reciprocal_rank, 4),
        f"ndcg@{k}": round(dcg / ideal if ideal else 1, 4),
    }
