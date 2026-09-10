"""Auditable orchestration for distinct RAG retrieval strategies."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from apps.api.graph import graph_relations
from apps.api.models import RetrievedProvision
from packages.ingestion.parser import normalize
from packages.retrieval.engine import CONCEPTS, Retriever, analyze_query


@dataclass
class RetrievalOutcome:
    results: list[RetrievedProvision]
    strategy: str
    query_variants: list[str] = field(default_factory=list)
    graph_edges: list[dict] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)


def expand_query(question: str, limit: int = 4) -> list[str]:
    """Create deterministic Vietnamese query variants that remain fully auditable."""
    normalized = normalize(question)
    variants = [question]
    for concept in analyze_query(question)["concepts"]:
        phrases = sorted(CONCEPTS[concept], key=len, reverse=True)
        matched = next((phrase for phrase in phrases if phrase in normalized), None)
        if not matched:
            continue
        for synonym in phrases:
            if synonym != matched:
                variants.append(normalized.replace(matched, synonym))
                break
        if len(variants) >= limit:
            break
    if "bhxh" in normalized and len(variants) < limit:
        variants.append(normalized.replace("bhxh", "bảo hiểm xã hội"))
    return list(dict.fromkeys(variants))[:limit]


def _multi_query(retriever: Retriever, variants: list[str], on: date, domain: str | None,
                 top_k: int) -> list[RetrievedProvision]:
    rankings = [retriever.search(query, on, domain, "L4", top_k * 3) for query in variants]
    combined: dict[str, RetrievedProvision] = {}
    rrf: dict[str, float] = {}
    hits: dict[str, int] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, 1):
            key = str(item.provision.id)
            rrf[key] = rrf.get(key, 0) + 1 / (60 + rank)
            hits[key] = hits.get(key, 0) + 1
            current = combined.get(key)
            if current is None or item.rerank_score > current.rerank_score:
                combined[key] = item
    for key, item in combined.items():
        # Preserve the legal rerank signal and add cross-query agreement as a small boost.
        item.rerank_score += rrf[key] * 2
        item.match_reasons.append(f"Multi-query: {hits[key]}/{len(variants)} nhánh")
    return sorted(combined.values(), key=lambda item: item.rerank_score, reverse=True)[:top_k]


def _graph_rerank(results: list[RetrievedProvision], top_k: int) -> tuple[list, list[dict], str]:
    seed_ids = {str(item.provision.document_id) for item in results[:3]}
    edges = graph_relations(seed_ids)
    if edges is None:
        return results[:top_k], [], "sql_fallback"
    neighbor_ids = {
        edge[key]
        for edge in edges
        for key in ("source_document_id", "target_document_id")
        if edge[key] not in seed_ids
    }
    for item in results:
        if str(item.provision.document_id) in neighbor_ids:
            item.rerank_score += 0.08
            item.match_reasons.append("Graph neighborhood: văn bản liên quan")
    return (sorted(results, key=lambda item: item.rerank_score, reverse=True)[:top_k],
            edges, "neo4j")


def retrieve(retriever: Retriever, question: str, on: date, domain: str | None,
             level: str, top_k: int) -> RetrievalOutcome:
    if level == "L0":
        return RetrievalOutcome([], "no_retrieval", trace=[{"stage": "retrieval", "count": 0}])
    if level in {"L1", "L2", "L3", "L4"}:
        results = retriever.search(question, on, domain, level, top_k)
        names = {"L1": "dense", "L2": "metadata_filtered", "L3": "hybrid_rrf",
                 "L4": "hybrid_legal_rerank"}
        return RetrievalOutcome(results, names[level], [question],
                                trace=[{"stage": "retrieve", "count": len(results)}])

    variants = expand_query(question) if level in {"L6", "L7"} else [question]
    candidates = (_multi_query(retriever, variants, on, domain, top_k * 3)
                  if len(variants) > 1 else retriever.search(question, on, domain, "L4", top_k * 3))
    trace = [{"stage": "query_expansion", "count": len(variants)},
             {"stage": "hybrid_retrieval", "count": len(candidates)}]
    edges: list[dict] = []
    graph_path = "not_used"
    if level in {"L5", "L7"}:
        candidates, edges, graph_path = _graph_rerank(candidates, top_k)
        trace.append({"stage": "graph_expansion", "count": len(edges), "path": graph_path})
    strategy = {"L5": "graph_rag", "L6": "multi_query_rag", "L7": "adaptive_rag"}[level]
    trace.append({"stage": "temporal_guard", "enabled": level == "L7"})
    return RetrievalOutcome(candidates[:top_k], strategy, variants, edges, trace)
