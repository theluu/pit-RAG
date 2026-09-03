import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from apps.api.config import settings
from apps.api.models import (
    CompareRequest,
    FeedbackRequest,
    LoginRequest,
    LoginResponse,
    QueryRequest,
    QueryResponse,
)
from apps.api.seed import load_seed
from packages.generation.grounded import generate
from packages.retrieval.engine import Retriever

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
DOCUMENTS, PROVISIONS = load_seed()
DOC_MAP = {d.id: d for d in DOCUMENTS}
RETRIEVER = Retriever(DOCUMENTS, PROVISIONS)
RUNS: dict[UUID, QueryResponse] = {}
FEEDBACK: dict[UUID, list[dict]] = defaultdict(list)
REQUESTS: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def rate_limit_and_trace(request: Request, call_next):
    key = request.client.host if request.client else "unknown"
    now = time.time()
    bucket = REQUESTS[key]
    while bucket and bucket[0] < now - 60:
        bucket.popleft()
    if len(bucket) >= settings.rate_limit_per_minute:
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
    bucket.append(now)
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


@app.get("/health")
def health():
    return {"status": "ok", "documents": len(DOCUMENTS), "provisions": len(PROVISIONS)}


@app.post("/api/v1/auth/login", response_model=LoginResponse)
def login(body: LoginRequest):
    if body.email != "demo@legalrag.vn" or body.password != "demo1234":
        raise HTTPException(401, "Invalid credentials")
    user = {"sub": "demo-user", "email": body.email, "role": "admin"}
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


def execute(body: QueryRequest) -> QueryResponse:
    started = time.perf_counter()
    results = (
        []
        if body.pipeline_level == "L0"
        else RETRIEVER.search(
            body.question, body.applicable_date, body.domain, body.pipeline_level, body.top_k
        )
    )
    answer, citations, confidence, warnings = generate(
        body.question, results, DOC_MAP, body.pipeline_level
    )
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
    response = QueryResponse(
        run_id=uuid4(),
        answer=answer,
        citations=citations,
        retrieved_provisions=results,
        confidence=confidence,
        warnings=warnings,
        pipeline_version=f"{body.pipeline_level}-deterministic-v1",
        latency_ms=max(1, round((time.perf_counter() - started) * 1000)),
        created_at=datetime.now(UTC),
    )
    RUNS[response.run_id] = response
    return response


@app.post("/api/v1/query", response_model=QueryResponse)
def query(body: QueryRequest, _: dict = Depends(current_user)):
    return execute(body)


@app.post("/api/v1/query/compare")
def compare(body: CompareRequest, _: dict = Depends(current_user)):
    return {
        level: execute(
            QueryRequest(
                question=body.question,
                applicable_date=body.applicable_date,
                domain=body.domain,
                pipeline_level=level,
            )
        )
        for level in body.pipelines
    }


@app.get("/api/v1/runs/{run_id}", response_model=QueryResponse)
def run(run_id: UUID, _: dict = Depends(current_user)):
    if run_id not in RUNS:
        raise HTTPException(404, "Run not found")
    return RUNS[run_id]


@app.post("/api/v1/runs/{run_id}/feedback", status_code=201)
def feedback(run_id: UUID, body: FeedbackRequest, user: dict = Depends(current_user)):
    if run_id not in RUNS:
        raise HTTPException(404, "Run not found")
    FEEDBACK[run_id].append(
        {**body.model_dump(), "user_id": user["sub"], "created_at": datetime.now(UTC).isoformat()}
    )
    return {"status": "recorded"}
