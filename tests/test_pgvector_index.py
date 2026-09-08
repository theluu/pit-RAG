"""Integration tests for the production pgvector path.

These exercise SQL that SQLite can never run: the HNSW ANN arm, the full-text arm and the
eligibility filters. Set `TEST_DATABASE_URL` to a pgvector-enabled PostgreSQL to run them,
e.g. `docker run -p 55432:5432 -e POSTGRES_PASSWORD=test pgvector/pgvector:pg16`.
"""

import os
from datetime import date

import pytest
from sqlalchemy import create_engine, text

from apps.api import database
from apps.api.config import settings

DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL (pgvector) is not configured")

DIMENSION = 8
TODAY = date(2026, 6, 1)


def unit(*values: float) -> list[float]:
    padded = list(values) + [0.0] * (DIMENSION - len(values))
    return padded[:DIMENSION]


DOCUMENTS = {
    "doc-labor": {"domain": "labor", "effective_from": "2020-01-01", "effective_to": None},
    "doc-expired": {"domain": "labor", "effective_from": "2015-01-01",
                    "effective_to": "2021-12-31"},
    "doc-tax": {"domain": "personal_income_tax", "effective_from": "2020-01-01",
                "effective_to": None},
}
# prov-near is the closest vector; prov-far is orthogonal; the others test the filters.
PROVISIONS = {
    "prov-near": ("doc-labor", "nghỉ hằng tuần ít nhất 24 giờ liên tục", unit(1.0, 0.0)),
    "prov-mid": ("doc-labor", "thời giờ làm thêm không quá 40 giờ", unit(0.8, 0.6)),
    "prov-far": ("doc-labor", "hồ sơ lưu trữ và con dấu", unit(0.0, 1.0)),
    "prov-expired": ("doc-expired", "nghỉ hằng tuần theo quy định cũ", unit(0.99, 0.1)),
    "prov-tax": ("doc-tax", "giảm trừ gia cảnh cho người phụ thuộc", unit(0.97, 0.2)),
}


@pytest.fixture(scope="module")
def pg(request):
    engine = create_engine(DSN, pool_pre_ping=True)
    with engine.begin() as connection:
        for table in ("provision_index_entries", "index_versions", "document_pages",
                      "ingestion_jobs", "document_files", "legal_provisions", "legal_documents"):
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS {table} CASCADE")
    return engine


@pytest.fixture
def indexed(pg, monkeypatch):
    monkeypatch.setattr(database, "engine", pg)
    monkeypatch.setattr(settings, "embedding_dimension", DIMENSION)
    database.Base.metadata.create_all(pg)
    with pg.begin() as connection:
        for statement in database.vector_ddl(DIMENSION):
            connection.exec_driver_sql(statement)
        connection.exec_driver_sql("TRUNCATE provision_index_entries, index_versions, "
                                   "legal_provisions, legal_documents CASCADE")
    with database.Session(pg) as session:
        for doc_id, payload in DOCUMENTS.items():
            session.add(database.DocumentRow(id=doc_id, document_number=doc_id,
                                             payload=payload, review_status="published"))
        session.flush()
        for pid, (doc_id, body, _) in PROVISIONS.items():
            session.add(database.ProvisionRow(id=pid, document_id=doc_id, content=body, payload={}))
        session.commit()
    version = database.create_index_version(
        "pg-index", "text-embedding-3-small", DIMENSION,
        [(pid, body, vector) for pid, (_, body, vector) in PROVISIONS.items()])
    assert database.activate_index(version)
    return version


def search(query="nghỉ hằng tuần", vector=None, domain=None, temporal=True, limit=10):
    return database.active_index_candidates(query, vector or unit(1.0, 0.05), TODAY,
                                            domain, temporal, limit)


def test_vectors_are_written_into_the_pgvector_column(indexed, pg):
    with pg.connect() as connection:
        missing = connection.execute(text(
            "SELECT count(*) FROM provision_index_entries WHERE embedding_vector IS NULL")).scalar()
    assert missing == 0


def test_ann_arm_returns_the_actual_nearest_neighbour_first(indexed):
    hits = search()
    assert "prov-near" in hits
    ranked = sorted(hits.items(), key=lambda item: item[1][0], reverse=True)
    assert ranked[0][0] == "prov-near"
    assert hits["prov-near"][0] > hits["prov-far"][0]


def test_ann_arm_truncates_by_distance_not_arbitrarily(indexed):
    """An unordered LIMIT would return an arbitrary slice instead of the closest rows."""
    hits = database.active_index_candidates("khong-co-tu-khoa-nao-trung", unit(1.0, 0.0),
                                            TODAY, None, False, limit=1)
    assert list(hits) == ["prov-near"]


def test_keyword_arm_scores_full_text_matches(indexed):
    hits = search(query="giảm trừ gia cảnh", vector=unit(0.0, 0.0, 1.0), domain=None)
    assert hits["prov-tax"][1] > 0


def test_hybrid_union_covers_both_arms(indexed):
    hits = search(query="con dấu", vector=unit(1.0, 0.0))
    assert hits["prov-near"][0] > 0 and hits["prov-near"][1] == 0
    assert hits["prov-far"][1] > 0


def test_temporal_filter_excludes_expired_documents(indexed):
    assert "prov-expired" not in search(temporal=True)
    assert "prov-expired" in search(temporal=False)


def test_domain_filter_is_applied(indexed):
    hits = search(domain="labor")
    assert "prov-tax" not in hits
    assert "prov-near" in hits


def test_unpublished_documents_are_never_served(indexed, pg):
    with database.Session(pg) as session:
        session.get(database.DocumentRow, "doc-labor").review_status = "review_ready"
        session.commit()
    hits = search()
    assert not any(pid.startswith("prov-near") for pid in hits)


def test_only_the_active_version_is_searched(indexed, pg):
    stale = database.create_index_version(
        "pg-index-stale", "text-embedding-3-small", DIMENSION,
        [("prov-far", "hồ sơ lưu trữ", unit(1.0, 0.0))])
    assert database.activate_index(stale)
    hits = search()
    assert list(hits) == ["prov-far"], "candidates leaked from a non-active index version"


def test_hnsw_index_is_used_by_the_ann_arm(indexed, pg):
    """The ANN arm must reach the HNSW index.

    Ordering by distance *after* an eligibility join (published / domain / effective-date)
    makes the index unusable, and PostgreSQL silently falls back to sorting the whole
    corpus. On a five-row fixture that costs nothing, so this test loads enough rows for
    the planner's choice to be meaningful.
    """
    import random

    rows = [{"v": database._vector_literal([random.random() for _ in range(DIMENSION)]),
             "p": f"bulk-{n}"} for n in range(5_000)]
    with pg.begin() as connection:
        connection.execute(text(
            "INSERT INTO legal_provisions (id, document_id, content, payload) "
            "VALUES (:p, 'doc-labor', 'nội dung', '{}')"), rows)
        connection.execute(text(
            "INSERT INTO provision_index_entries "
            "(index_version_id, provision_id, embedding, search_text, embedding_vector) "
            f"VALUES ('{indexed}', :p, '[]', 'nội dung', CAST(:v AS vector))"), rows)
        connection.exec_driver_sql("ANALYZE provision_index_entries")

    with pg.begin() as connection:
        connection.exec_driver_sql("SET LOCAL hnsw.iterative_scan = strict_order")
        statement = (database.ANN_SQL
                     .replace(":vector", f"'{database._vector_literal(unit(1.0))}'")
                     .replace(":version", f"'{indexed}'")
                     .replace(":overfetch", "80"))
        plan = "\n".join(row[0] for row in connection.exec_driver_sql("EXPLAIN " + statement))
    assert "ix_provision_embedding_hnsw" in plan, plan
