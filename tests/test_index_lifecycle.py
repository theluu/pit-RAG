"""Versioned production index: build, atomic activation, rollback and retention."""

import pytest
from sqlalchemy import create_engine

from apps.api import database
from apps.api.config import settings


@pytest.fixture
def store(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/index.db")
    monkeypatch.setattr(database, "engine", engine)
    database.Base.metadata.create_all(engine)
    with database.Session(engine) as session:
        session.add(database.DocumentRow(id="doc-1", document_number="TEST/2026/01",
                                         payload={"domain": "labor"}, review_status="published"))
        session.flush()
        session.add_all([database.ProvisionRow(id=f"prov-{n}", document_id="doc-1",
                                               content=f"Điều {n}", payload={}) for n in range(3)])
        session.commit()
    return engine


def build(name: str, dimension: int | None = None) -> str:
    dimension = dimension or settings.embedding_dimension
    entries = [(f"prov-{n}", f"điều {n}", [0.1] * dimension) for n in range(3)]
    return database.create_index_version(name, "text-embedding-3-small", dimension, entries)


def test_activation_is_exclusive_and_retires_the_predecessor(store):
    first, second = build("index-1"), build("index-2")
    assert database.activate_index(first)
    assert database.active_index_name() == "index-1"

    assert database.activate_index(second)
    assert database.active_index_name() == "index-2"
    statuses = {v["name"]: v["status"] for v in database.list_index_versions()}
    assert statuses == {"index-1": "retired", "index-2": "active"}


def test_a_retired_version_can_be_rolled_back_to(store):
    first, second = build("index-1"), build("index-2")
    database.activate_index(first)
    database.activate_index(second)
    assert database.activate_index(first)
    assert database.active_index_name() == "index-1"


def test_activation_rejects_a_dimension_mismatch(store, monkeypatch):
    """Serving an index built by a different embedding model would silently wreck recall."""
    version = build("index-wrong", dimension=8)
    monkeypatch.setattr(settings, "embedding_dimension", 1536)
    assert not database.activate_index(version)
    assert database.active_index_name() is None


def test_unknown_version_is_not_activated(store):
    assert not database.activate_index("00000000-0000-0000-0000-000000000000")


def test_retention_drops_entries_of_superseded_versions_but_keeps_the_active_one(store, monkeypatch):
    monkeypatch.setattr(settings, "index_retention", 2)
    versions = [build(f"index-{n}") for n in range(4)]
    active = versions[0]
    database.activate_index(active)  # activation prunes as a side effect

    surviving = {v["name"]: v["status"] for v in database.list_index_versions()}
    assert surviving["index-0"] == "active"
    with database.Session(store) as session:
        counts = {vid: session.query(database.ProvisionIndexRow)
                  .filter_by(index_version_id=vid).count() for vid in versions}
    assert counts[active] == 3, "the active index lost its entries"
    assert counts[versions[3]] == 3, "the most recent standby was pruned"
    assert counts[versions[1]] == 0 and counts[versions[2]] == 0
    assert surviving["index-1"] == "pruned"


def test_pruning_is_idempotent(store, monkeypatch):
    monkeypatch.setattr(settings, "index_retention", 1)
    database.activate_index(build("index-1"))
    build("index-2")
    assert database.prune_index_versions() == 1
    assert database.prune_index_versions() == 0


def test_sqlite_reports_no_ann_candidates(store):
    """Without pgvector the caller must fall back rather than receive silent garbage."""
    from datetime import date

    assert database.active_index_candidates("nghỉ hằng tuần", [0.1] * 4, date(2026, 6, 1),
                                            None, True) == {}
