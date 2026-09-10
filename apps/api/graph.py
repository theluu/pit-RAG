"""Optional Neo4j projection of the canonical SQL legal corpus.

SQL remains the source of truth. Every write is idempotent and graph outages never
prevent legal documents from being published or queried.
"""
from __future__ import annotations

from typing import Any

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError, ServiceUnavailable

from apps.api.config import settings
from apps.api.models import LegalDocument, Provision

_driver = None
_last_error: str | None = None
RELATION_TYPES = {
    "replaces": "REPLACES",
    "amends": "AMENDS",
    "supplements": "SUPPLEMENTS",
    "guides": "GUIDES",
}


def _get_driver():
    global _driver
    if not settings.neo4j_enabled:
        return None
    if _driver is None:
        _driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
            connection_timeout=1.5,
        )
    return _driver


def _record_error(exc: Exception) -> None:
    global _last_error
    _last_error = f"{type(exc).__name__}: {exc}"[:300]


def sync_graph(documents: list[LegalDocument], provisions: list[Provision],
               relations: list[dict]) -> bool:
    """Idempotently project the full published corpus into Neo4j."""
    global _last_error
    driver = _get_driver()
    if driver is None:
        return False
    docs = [{"id": str(d.id), "number": d.document_number, "title": d.title,
             "domain": d.domain, "authority": d.issuing_authority,
             "effective_from": d.effective_from.isoformat(),
             "effective_to": d.effective_to.isoformat() if d.effective_to else None}
            for d in documents]
    chunks = [{"id": str(p.id), "document_id": str(p.document_id), "article": p.article,
               "clause": p.clause, "point": p.point, "heading": p.heading}
              for p in provisions]
    try:
        with driver.session(database=settings.neo4j_database) as session:
            session.run("CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE").consume()
            session.run("CREATE CONSTRAINT provision_id IF NOT EXISTS FOR (p:Provision) REQUIRE p.id IS UNIQUE").consume()
            session.run("MATCH (p:Provision) WHERE NOT p.id IN $ids DETACH DELETE p",
                        ids=[row["id"] for row in chunks]).consume()
            session.run("MATCH (d:Document) WHERE NOT d.id IN $ids DETACH DELETE d",
                        ids=[row["id"] for row in docs]).consume()
            session.run("""
                UNWIND $rows AS row
                MERGE (d:Document {id: row.id}) SET d += row
            """, rows=docs).consume()
            session.run("""
                UNWIND $rows AS row
                MATCH (d:Document {id: row.document_id})
                MERGE (p:Provision {id: row.id}) SET p += row
                MERGE (d)-[:CONTAINS]->(p)
            """, rows=chunks).consume()
            for relation in relations:
                edge = RELATION_TYPES.get(relation["relation_type"])
                if not edge:
                    continue
                session.run(f"""
                    MATCH (source:Document {{id: $source_id}}), (target:Document {{id: $target_id}})
                    MERGE (source)-[r:{edge}]->(target)
                    SET r.effective_from = $effective_from, r.evidence_text = $evidence_text,
                        r.sql_relation_id = $relation_id
                """, source_id=relation["source_document_id"],
                    target_id=relation["target_document_id"],
                    effective_from=(relation["effective_from"].isoformat()
                                    if hasattr(relation["effective_from"], "isoformat")
                                    else relation["effective_from"]),
                    evidence_text=relation.get("evidence_text"), relation_id=relation.get("id")).consume()
        _last_error = None
        return True
    except (Neo4jError, ServiceUnavailable, OSError) as exc:
        _record_error(exc)
        return False


def graph_relations(document_ids: set[str]) -> list[dict] | None:
    """Return neighboring legal-document edges, or None when graph is unavailable."""
    driver = _get_driver()
    if driver is None:
        return None
    try:
        with driver.session(database=settings.neo4j_database) as session:
            result = session.run("""
                MATCH (source:Document)-[r]->(target:Document)
                WHERE type(r) IN ['REPLACES', 'AMENDS', 'SUPPLEMENTS', 'GUIDES']
                  AND (source.id IN $ids OR target.id IN $ids)
                RETURN r.sql_relation_id AS id, source.id AS source_document_id,
                       target.id AS target_document_id, toLower(type(r)) AS relation_type,
                       r.effective_from AS effective_from, r.evidence_text AS evidence_text
                ORDER BY id
            """, ids=list(document_ids))
            rows = [dict(record) for record in result]
        global _last_error
        _last_error = None
        return rows
    except (Neo4jError, ServiceUnavailable, OSError) as exc:
        _record_error(exc)
        return None


def graph_status() -> dict[str, Any]:
    driver = _get_driver()
    base = {"enabled": settings.neo4j_enabled, "available": False,
            "nodes": 0, "relationships": 0, "last_error": _last_error}
    if driver is None:
        return base
    try:
        with driver.session(database=settings.neo4j_database) as session:
            record = session.run(
                "MATCH (n) WITH count(n) AS nodes OPTIONAL MATCH ()-[r]->() "
                "RETURN nodes, count(r) AS relationships"
            ).single()
        base.update(available=True, nodes=record["nodes"],
                    relationships=record["relationships"], last_error=None)
        return base
    except (Neo4jError, ServiceUnavailable, OSError) as exc:
        _record_error(exc)
        base["last_error"] = _last_error
        return base
