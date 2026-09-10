from datetime import date

from apps.api.seed import load_seed
from packages.retrieval.engine import Retriever
from packages.retrieval.orchestrator import expand_query, retrieve


def test_multi_query_expansion_is_auditable_and_deduplicated():
    variants = expand_query("Năm 2026 đóng BHXH bao lâu để hưởng lương hưu?")
    assert variants[0].startswith("Năm 2026")
    assert any("bảo hiểm xã hội" in query for query in variants)
    assert len(variants) == len(set(variants))


def test_l6_fuses_multiple_rankings():
    documents, provisions = load_seed()
    outcome = retrieve(
        Retriever(documents, provisions),
        "Đóng BHXH bao nhiêu năm để hưởng lương hưu?",
        date(2026, 1, 1), "social_insurance", "L6", 5,
    )
    assert outcome.strategy == "multi_query_rag"
    assert len(outcome.query_variants) >= 2
    assert outcome.results
    assert any("Multi-query" in reason for reason in outcome.results[0].match_reasons)


def test_l5_uses_graph_neighbors(monkeypatch):
    documents, provisions = load_seed()
    monkeypatch.setattr(
        "packages.retrieval.orchestrator.graph_relations",
        lambda ids: [{"source_document_id": next(iter(ids)),
                      "target_document_id": "related", "relation_type": "replaces"}],
    )
    outcome = retrieve(
        Retriever(documents, provisions), "lương hưu", date(2026, 1, 1),
        "social_insurance", "L5", 5,
    )
    assert outcome.strategy == "graph_rag"
    assert outcome.graph_edges
    assert outcome.trace[-2]["stage"] == "graph_expansion"
