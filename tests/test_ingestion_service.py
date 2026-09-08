"""End-to-end ingestion: object store -> extraction -> parse -> provenance -> review."""

from uuid import uuid4

import pytest

from apps.api import database
from apps.api.config import settings
from packages.ingestion import service
from packages.ingestion.pdf_pipeline import PDFValidationError
from tests.test_pdf_pipeline import BORN_DIGITAL


@pytest.fixture
def uploaded(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/ingest.db")
    # Never let the suite reach the real provider; embedding is stubbed per test instead.
    monkeypatch.setattr(settings, "enable_openai", False)
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{tmp_path}/ingest.db")
    monkeypatch.setattr(database, "engine", engine)
    database.Base.metadata.create_all(engine)

    document_id, file_id, job_id = uuid4(), uuid4(), uuid4()
    pdf = BORN_DIGITAL
    with database.Session(engine) as session:
        session.add(database.DocumentRow(id=str(document_id), document_number="TEST/2026/01",
                                         payload={"id": str(document_id), "domain": "labor"},
                                         review_status="processing"))
        session.flush()
        session.add(database.DocumentFileRow(id=str(file_id), document_id=str(document_id),
                                             object_key="pdf/test.pdf", checksum="deadbeef",
                                             content_type="application/pdf", size_bytes=len(pdf)))
        session.flush()
        session.add(database.IngestionJobRow(id=str(job_id), document_id=str(document_id),
                                             file_id=str(file_id), status="queued", progress=5))
        session.commit()
    monkeypatch.setattr(service, "get_pdf", lambda key: pdf)
    return job_id, document_id, engine


def test_ingestion_produces_reviewable_provisions_with_provenance(uploaded):
    job_id, document_id, _ = uploaded
    service.process_ingestion(str(job_id))

    job = database.get_ingestion_job(job_id)
    assert job["status"] == "review_ready"
    assert job["progress"] == 100
    assert job["error"] is None

    preview = database.document_preview(document_id)
    assert preview["document"]["review_status"] == "review_ready"
    assert len(preview["pages"]) == 3
    assert all(page["extraction_method"] == "native" for page in preview["pages"])
    assert len(preview["provisions"]) == 5
    for provision in preview["provisions"]:
        assert provision["page_from"] is not None
        assert provision["extraction_method"] == "native"
        assert provision["quality_flags"] == []
    assert sorted(p["page_from"] for p in preview["provisions"]) == [1, 1, 2, 2, 3]


def test_ingestion_warns_when_embeddings_are_disabled(uploaded):
    job_id, _, _ = uploaded
    service.process_ingestion(str(job_id))
    warnings = database.get_ingestion_job(job_id)["warnings"]
    assert any("ENABLE_OPENAI" in warning for warning in warnings)


def test_ingestion_validates_every_chunk_against_the_embedding_provider(uploaded, monkeypatch):
    """A chunk that cannot be embedded must fail the job before it reaches review."""
    job_id, _, _ = uploaded
    monkeypatch.setattr(settings, "enable_openai", True)
    monkeypatch.setattr(settings, "embedding_dimension", 3)
    monkeypatch.setattr(service, "embed", lambda texts: [[0.1, 0.2, 0.3] for _ in texts])
    service.process_ingestion(str(job_id))
    job = database.get_ingestion_job(job_id)
    assert job["status"] == "review_ready"
    assert not any("ENABLE_OPENAI" in warning for warning in job["warnings"])

    monkeypatch.setattr(service, "embed", lambda texts: [[0.1, 0.2] for _ in texts])
    with pytest.raises(RuntimeError, match="invalid batch"):
        service.process_ingestion(str(job_id))
    assert database.get_ingestion_job(job_id)["status"] == "failed"


def test_reprocess_replaces_provisions_without_orphaning_index_entries(uploaded):
    """Re-running a job on an already indexed document must clear its index entries."""
    job_id, document_id, engine = uploaded
    service.process_ingestion(str(job_id))
    provisions = database.document_preview(document_id)["provisions"]
    version = database.create_index_version(
        "test-index", "text-embedding-3-small", 3,
        [(p["id"], p["normalized_content"], [0.1, 0.2, 0.3]) for p in provisions])

    service.process_ingestion(str(job_id))

    with database.Session(engine) as session:
        live = {row.id for row in session.query(database.ProvisionRow).all()}
        entries = session.query(database.ProvisionIndexRow).filter_by(
            index_version_id=version).all()
    assert live, "reprocessing dropped every provision"
    assert all(entry.provision_id in live for entry in entries)


def test_failed_ingestion_records_the_error(uploaded, monkeypatch):
    job_id, _, _ = uploaded
    monkeypatch.setattr(service, "get_pdf", lambda key: b"%PDF-1.4 broken")
    with pytest.raises(PDFValidationError):
        service.process_ingestion(str(job_id))
    job = database.get_ingestion_job(job_id)
    assert job["status"] == "failed"
    assert job["error"]
