import socket
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import jwt
import redis
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from apps.api.config import settings
from apps.api.database import (
    activate_index,
    active_index_name,
    admin_summary,
    audit,
    authenticate,
    create_index_version,
    create_upload_records,
    database_ready,
    document_preview,
    document_review_status,
    edit_provision,
    get_ingestion_job,
    get_run,
    init_database,
    latest_document_job,
    list_admin_documents,
    list_index_versions,
    list_relations,
    load_published_corpus,
    publish_document,
    published_provision_payloads,
    recent_audits,
    save_document,
    save_feedback,
    save_relation,
    save_run,
)
from apps.api.graph import graph_relations, graph_status, sync_graph
from apps.api.models import (
    CompareRequest,
    DocumentIngestRequest,
    FeedbackRequest,
    LegalDocument,
    LoginRequest,
    LoginResponse,
    Provision,
    ProvisionEditRequest,
    QueryRequest,
    QueryResponse,
    RelationRequest,
)
from apps.api.seed import load_seed
from packages.evaluation.runner import benchmark, load_cases
from packages.generation.grounded import generate
from packages.generation.openai_gateway import embed, provider_status
from packages.ingestion.parser import normalize, parse_legal_text
from packages.ingestion.pdf_pipeline import PDFValidationError, validate_pdf
from packages.ingestion.security import scan_upload
from packages.ingestion.storage import put_pdf, storage_ready
from packages.retrieval.engine import Retriever, analyze_query
from packages.retrieval.orchestrator import retrieve

app = FastAPI(
    title="Vietnam Legal RAG API",
    version="0.1.0",
    description="Citation-first Vietnamese legal retrieval API",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
SEED_DOCUMENTS, SEED_PROVISIONS = load_seed()
init_database(SEED_DOCUMENTS, SEED_PROVISIONS)
DOCUMENTS, PROVISIONS = load_published_corpus()
DOC_MAP = {d.id: d for d in DOCUMENTS}
RETRIEVER = Retriever(DOCUMENTS, PROVISIONS)
sync_graph(DOCUMENTS, PROVISIONS, list_relations())
RUNS: dict[UUID, QueryResponse] = {}
FEEDBACK: dict[UUID, list[dict]] = defaultdict(list)
REQUESTS: dict[str, deque] = defaultdict(deque)
REDIS = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=0.15, socket_timeout=0.15)


@app.middleware("http")
async def rate_limit_and_trace(request: Request, call_next):
    key = request.client.host if request.client else "unknown"
    now = time.time()
    exceeded = False
    try:
        window_key = f"rate:{key}:{int(now // 60)}"
        count = REDIS.incr(window_key)
        if count == 1:
            REDIS.expire(window_key, 65)
        exceeded = count > settings.rate_limit_per_minute
    except redis.RedisError:
        bucket = REQUESTS[key]
        while bucket and bucket[0] < now - 60:
            bucket.popleft()
        exceeded = len(bucket) >= settings.rate_limit_per_minute
        bucket.append(now)
    if exceeded:
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
    response = await call_next(request)
    response.headers["X-Trace-Id"] = request.headers.get("X-Trace-Id", str(uuid4()))
    return response


def current_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    try:
        return jwt.decode(authorization[7:], settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "Invalid or expired token") from exc


def require_role(user: dict, *roles: str) -> None:
    if user.get("role") not in roles:
        raise HTTPException(403, "Insufficient role")


@app.get("/health")
def health():
    return {"status": "ok", "documents": len(DOCUMENTS), "provisions": len(PROVISIONS),
            "active_index": active_index_name()}


def redis_ready() -> bool:
    parsed = urlparse(settings.redis_url)
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 6379), 0.15):
            return True
    except OSError:
        return False


@app.get("/ready")
def readiness():
    database = database_ready()
    index = bool(PROVISIONS) and (settings.app_env != "production" or bool(active_index_name()))
    return {
        "status": "ready" if database and index else "not_ready",
        "database": database,
        "redis": redis_ready(),
        "object_store": storage_ready(),
        "index": index,
        "active_index": active_index_name(),
        "provider": provider_status(),
        "neo4j": graph_status(),
    }


@app.get("/api/v1/capabilities")
def capabilities(_: dict = Depends(current_user)):
    return {
        "provider": provider_status(),
        "database": database_ready(),
        "redis": redis_ready(),
        "neo4j": graph_status(),
        "index_version": active_index_name() or "legacy-in-memory",
        "retrieval_modes": ["lexical", "hybrid_rrf", "temporal"],
        "ingestion": ["text", "html", "pdf_text"],
        "ocr": "paddleocr" if settings.ocr_enabled else "disabled",
        "embedding_dimension": settings.embedding_dimension,
    }


@app.post("/api/v1/auth/login", response_model=LoginResponse)
def login(body: LoginRequest):
    user = authenticate(body.email, body.password)
    if user is None:
        raise HTTPException(401, "Invalid credentials")
    token = jwt.encode(
        {**user, "exp": datetime.now(UTC) + timedelta(minutes=settings.access_token_minutes)},
        settings.secret_key,
        algorithm="HS256",
    )
    return LoginResponse(access_token=token, user=user)


@app.get("/api/v1/documents")
def documents(_: dict = Depends(current_user)):
    return DOCUMENTS


@app.get("/api/v1/documents/{document_id}")
def document(document_id: UUID, _: dict = Depends(current_user)):
    if document_id not in DOC_MAP:
        raise HTTPException(404, "Document not found")
    return {
        "document": DOC_MAP[document_id],
        "provisions": [p for p in PROVISIONS if p.document_id == document_id],
    }


@app.post("/api/v1/admin/documents", status_code=201)
def ingest_document(body: DocumentIngestRequest, user: dict = Depends(current_user)):
    require_role(user, "admin", "curator")
    if any(d.document_number == body.document_number for d in DOCUMENTS):
        raise HTTPException(409, "Document number already exists")
    parsed = parse_legal_text(body.text)
    if not parsed:
        raise HTTPException(422, "No Điều/Khoản structure could be parsed")
    doc_id = uuid5(NAMESPACE_URL, f"{body.document_number}:{sha256(body.text.encode()).hexdigest()}")
    document = LegalDocument(
        id=doc_id, document_number=body.document_number, title=body.title,
        document_type=body.document_type, issuing_authority=body.issuing_authority,
        issued_date=body.issued_date, effective_from=body.effective_from,
        effective_to=body.effective_to, source_url=body.source_url,
        checksum=sha256(body.text.encode()).hexdigest(), domain=body.domain,
        status="active" if body.publish else "draft",
    )
    provisions = [Provision(
        id=uuid5(doc_id, f"{p.article}-{p.clause}-{p.point}-{i}"), document_id=doc_id,
        chapter=p.chapter, article=p.article, clause=p.clause, point=p.point,
        heading=p.heading, content=p.content, normalized_content=normalize(p.content),
    ) for i, p in enumerate(parsed)]
    save_document(document, provisions, "published" if body.publish else "draft")
    audit(user["sub"], "document.ingest", str(doc_id), publish=body.publish,
          provision_count=len(provisions))
    if body.publish:
        DOCUMENTS.append(document)
        PROVISIONS.extend(provisions)
        DOC_MAP[document.id] = document
        global RETRIEVER
        RETRIEVER = Retriever(DOCUMENTS, PROVISIONS)
    return {"document": document, "provisions": provisions, "published": body.publish}


@app.post("/api/v1/admin/documents/uploads", status_code=202)
async def upload_document_pdf(
    file: UploadFile = File(...), document_number: str = Form(...), title: str = Form(...),
    document_type: str = Form(...), issuing_authority: str = Form(...),
    issued_date: str = Form(...), effective_from: str = Form(...),
    domain: str = Form(...), effective_to: str | None = Form(default=None),
    source_url: str | None = Form(default=None), user: dict = Depends(current_user),
):
    from datetime import date
    require_role(user, "admin", "curator")
    if domain not in {"labor", "social_insurance", "personal_income_tax"}:
        raise HTTPException(422, "Unknown domain")
    data = await file.read(settings.max_upload_bytes + 1)
    try:
        validate_pdf(data)
        scan_upload(data)
        issued = date.fromisoformat(issued_date)
        starts = date.fromisoformat(effective_from)
        ends = date.fromisoformat(effective_to) if effective_to else None
    except (PDFValidationError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    checksum = sha256(data).hexdigest()
    doc_id = uuid5(NAMESPACE_URL, f"{document_number}:{checksum}")
    file_id, job_id = uuid4(), uuid4()
    object_key = f"pdf/{doc_id}/{file_id}.pdf"
    document = LegalDocument(id=doc_id, document_number=document_number, title=title,
        document_type=document_type, issuing_authority=issuing_authority, issued_date=issued,
        effective_from=starts, effective_to=ends, domain=domain, source_url=source_url,
        checksum=checksum, status="processing")
    try:
        put_pdf(object_key, data)
        create_upload_records(document, file_id, object_key, checksum, len(data), job_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, "Object storage unavailable") from exc
    audit(user["sub"], "document.upload", str(doc_id), job_id=str(job_id), size_bytes=len(data))
    if settings.ingestion_eager:
        from packages.ingestion.service import process_ingestion
        process_ingestion(str(job_id))
    else:
        from apps.worker.tasks import ingest_pdf
        ingest_pdf.send(str(job_id))
    return {"document_id": doc_id, "job_id": job_id, "status": "queued"}


@app.get("/api/v1/admin/ingestion-jobs/{job_id}")
def ingestion_job(job_id: UUID, user: dict = Depends(current_user)):
    require_role(user, "admin", "curator")
    job = get_ingestion_job(job_id)
    if not job:
        raise HTTPException(404, "Ingestion job not found")
    return job


@app.get("/api/v1/admin/documents/{document_id}/preview")
def preview_document(document_id: UUID, user: dict = Depends(current_user)):
    require_role(user, "admin", "curator")
    preview = document_preview(document_id)
    if not preview:
        raise HTTPException(404, "Document not found")
    return preview


@app.patch("/api/v1/admin/documents/{document_id}/provisions/{provision_id}")
def update_preview_provision(document_id: UUID, provision_id: UUID, body: ProvisionEditRequest,
                             user: dict = Depends(current_user)):
    require_role(user, "admin", "curator")
    try:
        provision = edit_provision(document_id, provision_id, body.content, body.quality_flags)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not provision:
        raise HTTPException(404, "Provision not found")
    audit(user["sub"], "provision.edit", str(provision_id), document_id=str(document_id))
    return provision


@app.post("/api/v1/admin/documents/{document_id}/reprocess", status_code=202)
def reprocess_document(document_id: UUID, user: dict = Depends(current_user)):
    require_role(user, "admin", "curator")
    job = latest_document_job(document_id)
    if not job:
        raise HTTPException(404, "No ingestion job for document")
    from apps.worker.tasks import ingest_pdf
    ingest_pdf.send(job["id"])
    audit(user["sub"], "document.reprocess", str(document_id), job_id=job["id"])
    return {"job_id": job["id"], "status": "queued"}


def rebuild_production_index(extra_document_id: UUID | None = None,
                             required: bool = True) -> str | None:
    """Embed every published provision into a new, inactive index version.

    Returns None when the embedding provider is deliberately off and the caller can serve
    the deterministic lexical path instead; in `production` that degradation is an error.
    """
    # Only the embedding endpoint matters here; a chat outage must not block indexing.
    if not provider_status()["embeddings"]["available"]:
        if required and settings.app_env == "production":
            raise HTTPException(503, "Embedding provider unavailable; cannot build production index")
        return None
    payloads = published_provision_payloads(extra_document_id)
    if not payloads:
        raise HTTPException(422, "No provisions to index")
    vectors = []
    for offset in range(0, len(payloads), settings.embedding_batch_size):
        batch = payloads[offset:offset + settings.embedding_batch_size]
        embedded = embed([p["normalized_content"] for p in batch])
        if embedded is None or any(len(v) != settings.embedding_dimension for v in embedded):
            raise HTTPException(503, "Embedding provider unavailable or dimension mismatch")
        vectors.extend(embedded)
    name = f"legal-index-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"
    entries = [(p["id"], p["normalized_content"], vector) for p, vector in zip(payloads, vectors)]
    return create_index_version(name, settings.openai_embedding_model,
                                settings.embedding_dimension, entries)


def reload_corpus() -> None:
    global DOCUMENTS, PROVISIONS, DOC_MAP, RETRIEVER
    DOCUMENTS, PROVISIONS = load_published_corpus()
    DOC_MAP = {d.id: d for d in DOCUMENTS}
    RETRIEVER = Retriever(DOCUMENTS, PROVISIONS)


def refresh_graph() -> bool:
    return sync_graph(DOCUMENTS, PROVISIONS, list_relations())


@app.get("/api/v1/admin/summary")
def administration_summary(user: dict = Depends(current_user)):
    require_role(user, "admin", "curator", "evaluator")
    return {
        **admin_summary(),
        "capabilities": {
            "provider": provider_status(),
            "database": database_ready(),
            "redis": redis_ready(),
            "neo4j": graph_status(),
        },
        "published_index_documents": len(DOCUMENTS),
    }


@app.get("/api/v1/admin/documents")
def administration_documents(user: dict = Depends(current_user)):
    require_role(user, "admin", "curator")
    return list_admin_documents()


@app.post("/api/v1/admin/documents/{document_id}/publish")
def publish(document_id: UUID, user: dict = Depends(current_user)):
    require_role(user, "admin", "curator")
    status = document_review_status(document_id)
    if status not in {"draft", "review_ready"}:
        if status is None:
            raise HTTPException(404, "Document not found")
        raise HTTPException(409, f"Document is not publishable from status {status}")
    version_id = rebuild_production_index(document_id)
    if not publish_document(document_id):
        raise HTTPException(404, "Document not found")
    if version_id and not activate_index(version_id):
        raise HTTPException(500, "Index activation failed")
    audit(user["sub"], "document.publish", str(document_id))
    reload_corpus()
    graph_synced = refresh_graph()
    return {
        "status": "published",
        "document_id": document_id,
        "index_documents": len(DOCUMENTS),
        "index_provisions": len(PROVISIONS),
        "index_version": active_index_name() or "legacy-in-memory",
        "index_rebuilt": version_id is not None,
        "graph_synced": graph_synced,
    }


@app.get("/api/v1/admin/indexes")
def indexes(user: dict = Depends(current_user)):
    require_role(user, "admin", "curator", "evaluator")
    return list_index_versions()


@app.post("/api/v1/admin/indexes/rebuild", status_code=202)
def rebuild_index(user: dict = Depends(current_user)):
    require_role(user, "admin", "curator")
    version_id = rebuild_production_index(required=True)
    if version_id is None:
        raise HTTPException(503, "Embedding provider unavailable; enable ENABLE_OPENAI to build an index")
    audit(user["sub"], "index.rebuild", version_id)
    return {"id": version_id, "status": "ready"}


@app.post("/api/v1/admin/indexes/{version_id}/activate")
def activate_index_version(version_id: UUID, user: dict = Depends(current_user)):
    require_role(user, "admin", "curator")
    if not activate_index(version_id):
        raise HTTPException(409, "Index version is not ready")
    audit(user["sub"], "index.activate", str(version_id))
    return {"id": version_id, "status": "active", "name": active_index_name()}


@app.get("/api/v1/admin/audit")
def audit_log(user: dict = Depends(current_user)):
    require_role(user, "admin")
    return recent_audits()


@app.get("/api/v1/relations")
def relations(_: dict = Depends(current_user)):
    return list_relations()


@app.post("/api/v1/admin/relations", status_code=201)
def create_relation(body: RelationRequest, user: dict = Depends(current_user)):
    require_role(user, "admin", "curator")
    known = {d.id for d in DOCUMENTS}
    if body.source_document_id not in known or body.target_document_id not in known:
        raise HTTPException(422, "Both documents must be published")
    relation_id = save_relation(
        body.source_document_id,
        body.target_document_id,
        body.relation_type,
        body.effective_from,
        body.evidence_text,
    )
    audit(user["sub"], "relation.create", str(relation_id), relation_type=body.relation_type)
    graph_synced = refresh_graph()
    return {"id": relation_id, **body.model_dump(mode="json"), "graph_synced": graph_synced}


def execute(body: QueryRequest, user_id: str = "system", use_provider: bool = True) -> QueryResponse:
    started = time.perf_counter()
    retrieval = retrieve(
        RETRIEVER, body.question, body.applicable_date, body.domain,
        body.pipeline_level, body.top_k,
    )
    results = retrieval.results
    answer, citations, confidence, warnings, generation_mode = generate(
        body.question, results, DOC_MAP, body.pipeline_level, use_provider=use_provider
    )
    if body.pipeline_level != "L0" and RETRIEVER.index_degraded:
        warnings.append("Production vector index không khả dụng; đang dùng retrieval từ vựng.")
    if body.pipeline_level == "L7":
        excluded = [
            d
            for d in DOCUMENTS
            if (not body.domain or d.domain == body.domain)
            and d.effective_to
            and d.effective_to < body.applicable_date
        ]
        if excluded:
            warnings.append(
                "Đã loại văn bản hết hiệu lực tại ngày áp dụng: "
                + ", ".join(d.document_number for d in excluded)
            )
    cited_document_ids = {str(c.document_id) for c in citations}
    graph_timeline = (graph_relations(cited_document_ids)
                      if body.pipeline_level in {"L5", "L7"} else None)
    timeline = graph_timeline if graph_timeline is not None else [
        relation for relation in list_relations()
        if relation["source_document_id"] in cited_document_ids
        or relation["target_document_id"] in cited_document_ids
    ]
    response = QueryResponse(
        run_id=uuid4(),
        answer=answer,
        citations=citations,
        retrieved_provisions=results,
        confidence=confidence,
        warnings=warnings,
        pipeline_version=f"{body.pipeline_level}-deterministic-v1",
        index_version=(active_index_name() or "legacy-in-memory") if not RETRIEVER.index_degraded
        else "legacy-in-memory",
        latency_ms=max(1, round((time.perf_counter() - started) * 1000)),
        created_at=datetime.now(UTC),
        query_analysis=analyze_query(body.question),
        diagnostics={
            "candidate_count": len(results),
            "evidence_count": len(citations),
            "retrieved_document_numbers": [
                DOC_MAP[item.provision.document_id].document_number for item in results
            ],
            "effective_date_checked": body.pipeline_level in {"L2", "L3", "L4", "L7"},
            "abstained": not citations,
            "top_score": round(max((c.score for c in citations), default=0), 4),
            "generation_mode": generation_mode,
            "retrieval_strategy": retrieval.strategy,
            "query_variants": retrieval.query_variants,
            "execution_trace": retrieval.trace,
            "retrieval_path": ("lexical_fallback" if RETRIEVER.index_degraded
                               else ("pgvector_hybrid" if active_index_name() else "lexical")),
            "graph_path": ("neo4j" if graph_timeline is not None else "sql_fallback")
            if body.pipeline_level in {"L5", "L7"} else "not_used",
        },
        generation_mode=generation_mode,
        fallback_reason=(warnings[0] if generation_mode == "extractive_fallback" and warnings
                         else None),
        legal_timeline=timeline,
    )
    RUNS[response.run_id] = response
    save_run(user_id, body.question, body.applicable_date, body.domain, response)
    return response


@app.post("/api/v1/query", response_model=QueryResponse)
def query(body: QueryRequest, user: dict = Depends(current_user)):
    return execute(body, user["sub"])


@app.post("/api/v1/query/compare")
def compare(body: CompareRequest, user: dict = Depends(current_user)):
    return {
        level: execute(
            QueryRequest(
                question=body.question,
                applicable_date=body.applicable_date,
                domain=body.domain,
                pipeline_level=level,
            ),
            user["sub"],
        )
        for level in body.pipelines
    }


@app.get("/api/v1/runs/{run_id}", response_model=QueryResponse)
def run(run_id: UUID, _: dict = Depends(current_user)):
    stored = RUNS.get(run_id) or get_run(run_id)
    if stored is None:
        raise HTTPException(404, "Run not found")
    return stored


@app.post("/api/v1/runs/{run_id}/feedback", status_code=201)
def feedback(run_id: UUID, body: FeedbackRequest, user: dict = Depends(current_user)):
    if run_id not in RUNS and get_run(run_id) is None:
        raise HTTPException(404, "Run not found")
    FEEDBACK[run_id].append(
        {**body.model_dump(), "user_id": user["sub"], "created_at": datetime.now(UTC).isoformat()}
    )
    save_feedback(run_id, user["sub"], body.rating, body.comment)
    return {"status": "recorded"}


@app.post("/api/v1/admin/evaluations/{pipeline}")
def evaluate_pipeline(pipeline: str, user: dict = Depends(current_user)):
    require_role(user, "admin", "evaluator")
    if pipeline not in {"L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7"}:
        raise HTTPException(422, "Unknown pipeline")
    report = benchmark(
        load_cases("data/evaluation/sample.jsonl"),
        lambda request: execute(request, user["sub"], use_provider=False),
        pipeline,
    )
    audit(user["sub"], "evaluation.run", pipeline=pipeline, cases=report["cases"])
    return report
