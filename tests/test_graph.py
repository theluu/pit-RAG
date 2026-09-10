from datetime import date
from uuid import uuid4

from apps.api import graph
from apps.api.models import LegalDocument, Provision


class Result:
    def __init__(self, rows=None):
        self.rows = rows or []

    def consume(self):
        return None

    def __iter__(self):
        return iter(self.rows)

    def single(self):
        return {"nodes": 2, "relationships": 1}


class Session:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def run(self, query, **parameters):
        self.calls.append((query, parameters))
        if "RETURN r.sql_relation_id" in query:
            return Result([{"id": 7, "source_document_id": "a",
                            "target_document_id": "b", "relation_type": "replaces",
                            "effective_from": "2026-01-01", "evidence_text": "demo"}])
        return Result()


class Driver:
    def __init__(self):
        self.session_instance = Session()

    def session(self, **_):
        return self.session_instance


def test_graph_sync_and_query_are_idempotent(monkeypatch):
    driver = Driver()
    monkeypatch.setattr(graph.settings, "neo4j_enabled", True)
    monkeypatch.setattr(graph, "_driver", driver)
    document_id, provision_id = uuid4(), uuid4()
    document = LegalDocument(
        id=document_id, document_number="01/2026/QH", title="Test graph",
        document_type="Luật", issuing_authority="Quốc hội", issued_date=date(2026, 1, 1),
        effective_from=date(2026, 2, 1), checksum="abc", domain="labor",
    )
    provision = Provision(id=provision_id, document_id=document_id, article="1",
                          content="Nội dung", normalized_content="noi dung")
    relation = {"id": 7, "source_document_id": str(document_id),
                "target_document_id": str(document_id), "relation_type": "replaces",
                "effective_from": date(2026, 2, 1), "evidence_text": "demo"}

    assert graph.sync_graph([document], [provision], [relation]) is True
    assert any("MERGE (d:Document" in query for query, _ in driver.session_instance.calls)
    assert any("MERGE (d)-[:CONTAINS]->(p)" in query for query, _ in driver.session_instance.calls)
    assert any("[r:REPLACES]" in query for query, _ in driver.session_instance.calls)
    assert graph.graph_relations({"a"})[0]["relation_type"] == "replaces"
    assert graph.graph_status() == {"enabled": True, "available": True, "nodes": 2,
                                    "relationships": 1, "last_error": None}


def test_disabled_graph_is_an_explicit_safe_fallback(monkeypatch):
    monkeypatch.setattr(graph.settings, "neo4j_enabled", False)
    monkeypatch.setattr(graph, "_driver", None)
    assert graph.graph_relations({"any"}) is None
    assert graph.graph_status()["enabled"] is False
