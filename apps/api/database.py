from datetime import UTC, date, datetime
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    func,
    select,
    text,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from apps.api.config import settings
from apps.api.models import LegalDocument, Provision, QueryResponse


class Base(DeclarativeBase):
    pass


class DocumentRow(Base):
    __tablename__ = "legal_documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_number: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    review_status: Mapped[str] = mapped_column(String(20), default="published", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class ProvisionRow(Base):
    __tablename__ = "legal_provisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("legal_documents.id"), index=True)
    content: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON)


class DocumentFileRow(Base):
    __tablename__ = "document_files"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("legal_documents.id"), index=True)
    object_key: Mapped[str] = mapped_column(String(600), unique=True)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class IngestionJobRow(Base):
    __tablename__ = "ingestion_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("legal_documents.id"), index=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("document_files.id"))
    status: Mapped[str] = mapped_column(String(30), index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class DocumentPageRow(Base):
    __tablename__ = "document_pages"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("legal_documents.id"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    extraction_method: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    blocks: Mapped[list] = mapped_column(JSON, default=list)


class IndexVersionRow(Base):
    __tablename__ = "index_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    embedding_model: Mapped[str] = mapped_column(String(120))
    dimension: Mapped[int] = mapped_column(Integer)
    provision_count: Mapped[int] = mapped_column(Integer, default=0)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class ProvisionIndexRow(Base):
    __tablename__ = "provision_index_entries"
    index_version_id: Mapped[str] = mapped_column(ForeignKey("index_versions.id"), primary_key=True)
    provision_id: Mapped[str] = mapped_column(ForeignKey("legal_provisions.id"), primary_key=True)
    embedding: Mapped[list] = mapped_column(JSON)
    search_text: Mapped[str] = mapped_column(Text)


class RelationRow(Base):
    __tablename__ = "document_relations"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_document_id: Mapped[str] = mapped_column(String(36), index=True)
    target_document_id: Mapped[str] = mapped_column(String(36), index=True)
    relation_type: Mapped[str] = mapped_column(String(30))
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[str] = mapped_column(String(20), default="draft")


class RunRow(Base):
    __tablename__ = "rag_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True)
    question: Mapped[str] = mapped_column(Text)
    pipeline_level: Mapped[str] = mapped_column(String(10), index=True)
    applicable_date: Mapped[date] = mapped_column(Date)
    domain: Mapped[str | None] = mapped_column(String(40), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class FeedbackRow(Base):
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("rag_runs.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(100))
    rating: Mapped[str] = mapped_column(String(30))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class AuditRow(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    actor_id: Mapped[str] = mapped_column(String(100), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class UserRow(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(30), default="user")
    active: Mapped[bool] = mapped_column(default=True)


engine = create_engine(settings.database_url, pool_pre_ping=True)
password_hasher = PasswordHasher()

# The progress value the worker writes when a run starts; used to count attempts once per
# run rather than once per progress tick.
EXTRACT_FLOOR_PROGRESS = 15


def vector_ddl(dimension: int | None = None) -> list[str]:
    """PostgreSQL-only statements that turn the entry table into a production ANN index.

    Kept here so `init_database` and the Alembic migration cannot drift apart.
    """
    dimension = dimension or settings.embedding_dimension
    return [
        "CREATE EXTENSION IF NOT EXISTS vector",
        "CREATE EXTENSION IF NOT EXISTS unaccent",
        ("ALTER TABLE provision_index_entries ADD COLUMN IF NOT EXISTS "
         f"embedding_vector vector({dimension})"),
        ("CREATE INDEX IF NOT EXISTS ix_provision_embedding_hnsw ON "
         "provision_index_entries USING hnsw (embedding_vector vector_cosine_ops)"),
        ("CREATE INDEX IF NOT EXISTS ix_provision_search_gin ON provision_index_entries "
         "USING gin (to_tsvector('simple', search_text))"),
        # The ANN pre-filter selects one index version, so that column needs its own index.
        ("CREATE INDEX IF NOT EXISTS ix_provision_entries_version ON provision_index_entries "
         "(index_version_id)"),
    ]


def init_database(documents: list[LegalDocument], provisions: list[Provision]) -> None:
    Base.metadata.create_all(engine)
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            for statement in vector_ddl():
                connection.exec_driver_sql(statement)
    with Session(engine) as session:
        if not session.scalar(select(UserRow).where(UserRow.email == "demo@legalrag.vn")):
            session.add(UserRow(id="demo-user", email="demo@legalrag.vn",
                                password_hash=password_hasher.hash("demo1234"), role="admin"))
        for document in documents:
            if not session.get(DocumentRow, str(document.id)):
                session.add(DocumentRow(id=str(document.id), document_number=document.document_number,
                                        payload=document.model_dump(mode="json")))
        for provision in provisions:
            if not session.get(ProvisionRow, str(provision.id)):
                session.add(ProvisionRow(id=str(provision.id), document_id=str(provision.document_id),
                                         content=provision.content, payload=provision.model_dump(mode="json")))
        by_number = {document.document_number: document for document in documents}
        old_law = by_number.get("58/2014/QH13")
        new_law = by_number.get("41/2024/QH15")
        if old_law and new_law and not session.scalar(
            select(RelationRow).where(
                RelationRow.source_document_id == str(new_law.id),
                RelationRow.target_document_id == str(old_law.id),
                RelationRow.relation_type == "replaces",
            )
        ):
            session.add(RelationRow(
                source_document_id=str(new_law.id), target_document_id=str(old_law.id),
                relation_type="replaces", effective_from=new_law.effective_from,
                evidence_text="Luật BHXH 2024 thay thế Luật BHXH 2014 trong corpus demo.",
                review_status="published",
            ))
        session.commit()


def authenticate(email: str, password: str) -> dict[str, str] | None:
    with Session(engine) as session:
        user = session.scalar(select(UserRow).where(UserRow.email == email))
        if not user or not user.active:
            return None
        try:
            password_hasher.verify(user.password_hash, password)
        except VerifyMismatchError:
            return None
        if password_hasher.check_needs_rehash(user.password_hash):
            user.password_hash = password_hasher.hash(password)
            session.commit()
        return {"sub": user.id, "email": user.email, "role": user.role}


def save_run(user_id: str, question: str, applicable_date, domain: str | None,
             response: QueryResponse) -> None:
    with Session(engine) as session:
        session.merge(RunRow(id=str(response.run_id), user_id=user_id, question=question,
                             pipeline_level=response.pipeline_version.split("-")[0],
                             applicable_date=applicable_date, domain=domain,
                             payload=response.model_dump(mode="json")))
        session.commit()


def get_run(run_id: UUID) -> QueryResponse | None:
    with Session(engine) as session:
        row = session.get(RunRow, str(run_id))
        return QueryResponse.model_validate(row.payload) if row else None


def save_feedback(run_id: UUID, user_id: str, rating: str, comment: str | None) -> None:
    with Session(engine) as session:
        session.add(FeedbackRow(run_id=str(run_id), user_id=user_id, rating=rating, comment=comment))
        session.commit()


def audit(actor_id: str, action: str, resource_id: str | None = None, **details) -> None:
    with Session(engine) as session:
        session.add(AuditRow(actor_id=actor_id, action=action, resource_id=resource_id, details=details))
        session.commit()


def save_document(document: LegalDocument, provisions: list[Provision], review_status: str) -> None:
    with Session(engine) as session:
        session.add(DocumentRow(id=str(document.id), document_number=document.document_number,
                                payload=document.model_dump(mode="json"), review_status=review_status))
        session.add_all([
            ProvisionRow(id=str(p.id), document_id=str(p.document_id), content=p.content,
                         payload=p.model_dump(mode="json")) for p in provisions
        ])
        session.commit()


def load_published_corpus() -> tuple[list[LegalDocument], list[Provision]]:
    with Session(engine) as session:
        document_rows = session.scalars(
            select(DocumentRow).where(DocumentRow.review_status == "published")
        ).all()
        document_ids = {row.id for row in document_rows}
        provision_rows = session.scalars(
            select(ProvisionRow).where(ProvisionRow.document_id.in_(document_ids))
        ).all() if document_ids else []
        return (
            [LegalDocument.model_validate(row.payload) for row in document_rows],
            [Provision.model_validate(row.payload) for row in provision_rows],
        )


def admin_summary() -> dict:
    with Session(engine) as session:
        status_rows = session.execute(
            select(DocumentRow.review_status, func.count()).group_by(DocumentRow.review_status)
        ).all()
        return {
            "documents": sum(count for _, count in status_rows),
            "documents_by_status": dict(status_rows),
            "provisions": session.scalar(select(func.count()).select_from(ProvisionRow)) or 0,
            "runs": session.scalar(select(func.count()).select_from(RunRow)) or 0,
            "feedback": session.scalar(select(func.count()).select_from(FeedbackRow)) or 0,
            "audit_events": session.scalar(select(func.count()).select_from(AuditRow)) or 0,
        }


def list_admin_documents() -> list[dict]:
    with Session(engine) as session:
        rows = session.scalars(select(DocumentRow).order_by(DocumentRow.created_at.desc())).all()
        return [{**row.payload, "review_status": row.review_status} for row in rows]


def publish_document(document_id: UUID) -> bool:
    with Session(engine) as session:
        row = session.get(DocumentRow, str(document_id))
        if not row:
            return False
        payload = dict(row.payload)
        payload["status"] = "active"
        row.payload = payload
        row.review_status = "published"
        session.commit()
        return True


def document_review_status(document_id: UUID | str) -> str | None:
    with Session(engine) as session:
        row = session.get(DocumentRow, str(document_id))
        return row.review_status if row else None


def save_relation(source_document_id: UUID, target_document_id: UUID, relation_type: str,
                  effective_from: date | None, evidence_text: str | None) -> int:
    with Session(engine) as session:
        relation = RelationRow(source_document_id=str(source_document_id),
                               target_document_id=str(target_document_id),
                               relation_type=relation_type, effective_from=effective_from,
                               evidence_text=evidence_text, review_status="published")
        session.add(relation)
        session.commit()
        session.refresh(relation)
        return relation.id


def list_relations() -> list[dict]:
    with Session(engine) as session:
        rows = session.scalars(select(RelationRow).order_by(RelationRow.id)).all()
        return [{"id": row.id, "source_document_id": row.source_document_id,
                 "target_document_id": row.target_document_id, "relation_type": row.relation_type,
                 "effective_from": row.effective_from, "evidence_text": row.evidence_text}
                for row in rows]


def recent_audits(limit: int = 30) -> list[dict]:
    with Session(engine) as session:
        rows = session.scalars(select(AuditRow).order_by(AuditRow.created_at.desc()).limit(limit)).all()
        return [{"actor_id": row.actor_id, "action": row.action,
                 "resource_id": row.resource_id, "details": row.details,
                 "created_at": row.created_at} for row in rows]


def database_ready() -> bool:
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        return True
    except SQLAlchemyError:
        return False


def create_upload_records(document: LegalDocument, file_id: UUID, object_key: str, checksum: str,
                          size_bytes: int, job_id: UUID) -> None:
    with Session(engine) as session:
        duplicate = session.scalar(select(DocumentFileRow).where(DocumentFileRow.checksum == checksum))
        if duplicate:
            raise ValueError("This PDF has already been uploaded")
        if session.scalar(select(DocumentRow).where(DocumentRow.document_number == document.document_number)):
            raise ValueError("Document number already exists")
        session.add(DocumentRow(id=str(document.id), document_number=document.document_number,
                                payload=document.model_dump(mode="json"), review_status="processing"))
        # These mappings deliberately avoid ORM relationships; flush the parent first so
        # PostgreSQL can enforce the file/job foreign keys deterministically.
        session.flush()
        session.add(DocumentFileRow(id=str(file_id), document_id=str(document.id),
                                    object_key=object_key, checksum=checksum,
                                    content_type="application/pdf", size_bytes=size_bytes))
        session.flush()
        session.add(IngestionJobRow(id=str(job_id), document_id=str(document.id), file_id=str(file_id),
                                    status="queued", progress=5))
        session.commit()


def get_ingestion_job(job_id: UUID | str) -> dict | None:
    with Session(engine) as session:
        row = session.get(IngestionJobRow, str(job_id))
        if not row:
            return None
        return {"id": row.id, "document_id": row.document_id, "file_id": row.file_id,
                "status": row.status, "progress": row.progress, "attempt": row.attempt,
                "error": row.error, "warnings": row.warnings,
                "created_at": row.created_at, "updated_at": row.updated_at}


def latest_document_job(document_id: UUID | str) -> dict | None:
    with Session(engine) as session:
        row = session.scalar(select(IngestionJobRow).where(
            IngestionJobRow.document_id == str(document_id)).order_by(
                IngestionJobRow.created_at.desc()).limit(1))
        return get_ingestion_job(row.id) if row else None


def edit_provision(document_id: UUID | str, provision_id: UUID | str, content: str,
                   quality_flags: list[str]) -> dict | None:
    from packages.ingestion.parser import normalize
    with Session(engine) as session:
        document = session.get(DocumentRow, str(document_id))
        row = session.get(ProvisionRow, str(provision_id))
        if not document or not row or row.document_id != str(document_id):
            return None
        if document.review_status not in {"draft", "review_ready"}:
            raise ValueError("Published provisions cannot be edited in place")
        payload = dict(row.payload)
        payload.update(content=content, normalized_content=normalize(content),
                       quality_flags=quality_flags, revision=int(payload.get("revision", 1)) + 1,
                       extraction_method="manual")
        row.content, row.payload = content, payload
        session.commit()
        return payload


def update_ingestion_job(job_id: UUID | str, status: str, progress: int,
                         error: str | None = None, warnings: list | None = None) -> None:
    with Session(engine) as session:
        row = session.get(IngestionJobRow, str(job_id))
        if not row:
            raise ValueError("Unknown ingestion job")
        row.status, row.progress, row.error = status, progress, error
        row.updated_at = datetime.now(UTC)
        if warnings is not None:
            row.warnings = warnings
        if status == "extracting" and row.progress <= EXTRACT_FLOOR_PROGRESS:
            # Count one attempt per run, not once per progress tick.
            row.attempt += 1
        if status == "failed":
            # Otherwise the document sits in `processing` forever with no route out.
            document = session.get(DocumentRow, row.document_id)
            if document and document.review_status == "processing":
                document.review_status = "failed"
        session.commit()


def ingestion_job_context(job_id: UUID | str) -> dict | None:
    with Session(engine) as session:
        job = session.get(IngestionJobRow, str(job_id))
        if not job:
            return None
        file = session.get(DocumentFileRow, job.file_id)
        document = session.get(DocumentRow, job.document_id)
        return {"job_id": job.id, "document_id": job.document_id, "file_id": job.file_id,
                "object_key": file.object_key, "document": document.payload}


def save_extracted_document(job_id: UUID | str, pages: list[dict], provisions: list[Provision],
                            warnings: list[str]) -> None:
    with Session(engine) as session:
        job = session.get(IngestionJobRow, str(job_id))
        document = session.get(DocumentRow, job.document_id)
        file = session.get(DocumentFileRow, job.file_id)
        session.query(DocumentPageRow).filter_by(document_id=job.document_id).delete()
        # Index entries reference provisions; drop them first or reprocessing an already
        # indexed document violates the foreign key on PostgreSQL.
        stale = session.scalars(select(ProvisionRow.id).where(
            ProvisionRow.document_id == job.document_id)).all()
        if stale:
            session.query(ProvisionIndexRow).filter(
                ProvisionIndexRow.provision_id.in_(stale)).delete(synchronize_session=False)
        session.query(ProvisionRow).filter_by(document_id=job.document_id).delete()
        session.add_all([DocumentPageRow(document_id=job.document_id, **page) for page in pages])
        session.add_all([ProvisionRow(id=str(p.id), document_id=str(p.document_id), content=p.content,
                                     payload=p.model_dump(mode="json")) for p in provisions])
        file.page_count = len(pages)
        document.review_status = "review_ready"
        job.status, job.progress, job.warnings, job.error = "review_ready", 100, warnings, None
        job.updated_at = datetime.now(UTC)
        session.commit()


def document_preview(document_id: UUID | str) -> dict | None:
    with Session(engine) as session:
        document = session.get(DocumentRow, str(document_id))
        if not document:
            return None
        pages = session.scalars(select(DocumentPageRow).where(
            DocumentPageRow.document_id == str(document_id)).order_by(DocumentPageRow.page_number)).all()
        provisions = session.scalars(select(ProvisionRow).where(
            ProvisionRow.document_id == str(document_id))).all()
        return {"document": {**document.payload, "review_status": document.review_status},
                "pages": [{"page_number": p.page_number, "text": p.text,
                           "extraction_method": p.extraction_method,
                           "confidence": p.confidence, "blocks": p.blocks} for p in pages],
                "provisions": [p.payload for p in provisions]}


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in embedding) + "]"


def create_index_version(name: str, model: str, dimension: int, entries: list[tuple[str, str, list[float]]],
                         status: str = "ready") -> str:
    from uuid import uuid4
    version_id = str(uuid4())
    with Session(engine) as session:
        session.add(IndexVersionRow(id=version_id, name=name, status=status,
                                    embedding_model=model, dimension=dimension,
                                    provision_count=len(entries)))
        session.add_all([ProvisionIndexRow(index_version_id=version_id, provision_id=pid,
                                          search_text=search_text, embedding=embedding)
                         for pid, search_text, embedding in entries])
        session.commit()
    if engine.dialect.name == "postgresql" and entries:
        # One statement per row makes a full rebuild O(corpus) round trips; send them
        # as a single executemany batch instead.
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE provision_index_entries SET embedding_vector=CAST(:vector AS vector) "
                     "WHERE index_version_id=:version AND provision_id=:provision"),
                [{"vector": _vector_literal(embedding), "version": version_id, "provision": pid}
                 for pid, _, embedding in entries],
            )
    return version_id


def activate_index(version_id: UUID | str) -> bool:
    with Session(engine) as session:
        version = session.get(IndexVersionRow, str(version_id))
        # "retired" is reactivatable so a bad index can be rolled back to its predecessor.
        if not version or version.status not in {"ready", "active", "retired"}:
            return False
        if version.dimension != settings.embedding_dimension:
            return False
        session.query(IndexVersionRow).filter(IndexVersionRow.status == "active").update(
            {IndexVersionRow.status: "retired", IndexVersionRow.activated_at: None})
        version.status, version.activated_at = "active", datetime.now(UTC)
        session.commit()
    prune_index_versions()
    return True


def prune_index_versions(keep: int | None = None) -> int:
    """Drop entry rows of superseded versions so the ANN table stays proportional to the corpus.

    The version rows themselves are retained as an audit trail of what was ever served.
    """
    keep = settings.index_retention if keep is None else keep
    with Session(engine) as session:
        superseded = session.scalars(
            select(IndexVersionRow.id)
            .where(IndexVersionRow.status.not_in(("active", "pruned")))
            .order_by(IndexVersionRow.created_at.desc()).offset(max(keep - 1, 0))
        ).all()
        if not superseded:
            return 0
        session.query(ProvisionIndexRow).filter(
            ProvisionIndexRow.index_version_id.in_(superseded)).delete(synchronize_session=False)
        session.query(IndexVersionRow).filter(IndexVersionRow.id.in_(superseded)).update(
            {IndexVersionRow.status: "pruned"}, synchronize_session=False)
        session.commit()
        return len(superseded)


def list_index_versions() -> list[dict]:
    with Session(engine) as session:
        rows = session.scalars(select(IndexVersionRow).order_by(IndexVersionRow.created_at.desc())).all()
        return [{"id": r.id, "name": r.name, "status": r.status,
                 "embedding_model": r.embedding_model, "dimension": r.dimension,
                 "provision_count": r.provision_count, "activated_at": r.activated_at,
                 "created_at": r.created_at} for r in rows]


def active_index_name() -> str | None:
    with Session(engine) as session:
        row = session.scalar(select(IndexVersionRow).where(IndexVersionRow.status == "active"))
        return row.name if row else None


def active_index_id() -> str | None:
    with Session(engine) as session:
        row = session.scalar(select(IndexVersionRow).where(IndexVersionRow.status == "active"))
        return row.id if row else None


def _enable_iterative_scan(connection) -> None:
    """Ask pgvector to keep scanning until the post-filter is satisfied (pgvector >= 0.8).

    The ANN arm filters on index_version_id *after* the index scan, so without this a
    query can come back with fewer rows than requested. Older servers do not have the GUC,
    and a failed SET would poison the transaction, so it runs inside a savepoint.
    """
    savepoint = connection.begin_nested()
    try:
        connection.exec_driver_sql("SET LOCAL hnsw.iterative_scan = strict_order")
        savepoint.commit()
    except SQLAlchemyError:
        savepoint.rollback()


# pgvector rejects hnsw.ef_search outside 1..1000 instead of clamping it, and the error
# aborts the whole statement. L5-L7 over-fetch well past 1000, so the ceiling has to be
# applied here rather than left to PostgreSQL.
HNSW_EF_SEARCH_MAX = 1000


def _ef_search(overfetch: int) -> int:
    return min(max(settings.hnsw_ef_search, overfetch), HNSW_EF_SEARCH_MAX)


# The approximate-nearest-neighbour arm, kept as a constant so tests can EXPLAIN exactly
# what production runs. It touches only provision_index_entries with an equality filter:
# joining index_versions here makes the plan fall back to a sequential scan plus sort.
ANN_SQL = """
          SELECT provision_id, embedding_vector <=> CAST(:vector AS vector) AS distance
          FROM provision_index_entries
          WHERE index_version_id = :version AND embedding_vector IS NOT NULL
          ORDER BY embedding_vector <=> CAST(:vector AS vector)
          LIMIT :overfetch
"""


def active_index_candidates(query: str, query_embedding: list[float], on: date,
                            domain: str | None, temporal: bool, limit: int = 50) -> dict[str, tuple[float, float]]:
    """Hybrid ANN + full-text candidate generation against the active index version.

    Both arms order before they truncate: an unordered LIMIT returns an arbitrary slice
    rather than the nearest neighbours. The vector arm also queries the entry table with a
    plain equality filter and over-fetches *before* the eligibility join, because joining
    index_versions (or pre-filtering by document metadata) stops PostgreSQL from using the
    HNSW index at all and silently degrades into sorting the whole corpus.
    """
    if engine.dialect.name != "postgresql":
        return {}
    version_id = active_index_id()
    if not version_id:
        return {}
    vector = _vector_literal(query_embedding)
    overfetch = max(limit * max(settings.ann_overfetch, 1), limit)
    sql = text("""
        WITH ann AS (""" + ANN_SQL + """), eligible AS (
          SELECT e.provision_id, e.search_text
          FROM provision_index_entries e
          JOIN legal_provisions p ON p.id = e.provision_id
          JOIN legal_documents d ON d.id = p.document_id
          WHERE e.index_version_id = :version
            AND d.review_status = 'published'
            -- Every bind needs an explicit cast: PostgreSQL cannot infer the type of a
            -- NULL parameter used only in `IS NULL`, and rejects the whole statement.
            AND (CAST(:domain AS text) IS NULL OR d.payload->>'domain' = CAST(:domain AS text))
            AND (NOT CAST(:temporal AS boolean) OR (
              CAST(d.payload->>'effective_from' AS date) <= CAST(:on_date AS date) AND
              (d.payload->>'effective_to' IS NULL
               OR CAST(d.payload->>'effective_to' AS date) >= CAST(:on_date AS date))
            ))
        ), vector_hits AS (
          SELECT ann.provision_id, 1 - ann.distance AS score
          FROM ann JOIN eligible ON eligible.provision_id = ann.provision_id
          ORDER BY ann.distance
          LIMIT :limit
        ), keyword_hits AS (
          SELECT provision_id,
                 ts_rank_cd(to_tsvector('simple', search_text),
                            websearch_to_tsquery('simple', CAST(:query AS text))) AS score
          FROM eligible
          WHERE to_tsvector('simple', search_text)
                @@ websearch_to_tsquery('simple', CAST(:query AS text))
          ORDER BY score DESC
          LIMIT :limit
        )
        SELECT COALESCE(v.provision_id, k.provision_id) AS provision_id,
               COALESCE(v.score, 0) AS vector_score, COALESCE(k.score, 0) AS keyword_score
        FROM vector_hits v FULL OUTER JOIN keyword_hits k ON k.provision_id = v.provision_id
    """)
    with engine.begin() as connection:
        # HNSW recall is bounded by ef_search; the default (40) is below our over-fetch.
        # SET LOCAL only applies inside an explicit transaction block.
        connection.exec_driver_sql(
            f"SET LOCAL hnsw.ef_search = {_ef_search(overfetch)}")
        _enable_iterative_scan(connection)
        rows = connection.execute(sql, {"domain": domain, "temporal": temporal, "on_date": on,
            "vector": vector, "query": query, "limit": limit, "version": version_id,
            "overfetch": overfetch}).mappings().all()
    return {row["provision_id"]: (float(row["vector_score"]), float(row["keyword_score"]))
            for row in rows}


def published_provision_payloads(extra_document_id: UUID | str | None = None) -> list[dict]:
    with Session(engine) as session:
        docs = session.scalars(select(DocumentRow)).all()
        ids = {d.id for d in docs if d.review_status == "published" or
               (extra_document_id and d.id == str(extra_document_id))}
        rows = session.scalars(select(ProvisionRow).where(ProvisionRow.document_id.in_(ids))).all()
        return [row.payload for row in rows]
