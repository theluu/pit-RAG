from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

Domain = Literal["labor", "social_insurance", "personal_income_tax"]
Pipeline = Literal["L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7"]


class LegalDocument(BaseModel):
    id: UUID
    document_number: str
    title: str
    document_type: str
    issuing_authority: str
    issued_date: date
    effective_from: date
    effective_to: date | None = None
    status: str = "active"
    source_url: str | None = None
    checksum: str
    version: int = 1
    domain: Domain


class Provision(BaseModel):
    id: UUID
    document_id: UUID
    chapter: str | None = None
    article: str
    clause: str | None = None
    point: str | None = None
    heading: str | None = None
    content: str
    normalized_content: str
    page_from: int | None = None
    page_to: int | None = None
    extraction_method: Literal["native", "ocr", "mixed", "manual"] = "manual"
    extraction_confidence: float | None = None
    quality_flags: list[str] = Field(default_factory=list)
    revision: int = 1


class Citation(BaseModel):
    provision_id: UUID
    document_id: UUID
    document_number: str
    title: str
    article: str
    clause: str | None = None
    point: str | None = None
    quote: str
    source_url: str | None = None
    score: float


class RetrievedProvision(BaseModel):
    provision: Provision
    vector_score: float = 0
    keyword_score: float = 0
    fusion_score: float = 0
    rerank_score: float = 0
    match_reasons: list[str] = Field(default_factory=list)


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    applicable_date: date = Field(default_factory=date.today)
    domain: Domain | None = None
    pipeline_level: Pipeline = "L4"
    top_k: int = Field(default=5, ge=1, le=20)


class QueryResponse(BaseModel):
    run_id: UUID
    answer: str
    citations: list[Citation]
    retrieved_provisions: list[RetrievedProvision]
    confidence: float
    warnings: list[str]
    pipeline_version: str
    latency_ms: int
    estimated_cost: float = 0
    created_at: datetime
    query_analysis: dict = Field(default_factory=dict)
    diagnostics: dict = Field(default_factory=dict)
    generation_mode: Literal["openai", "extractive_fallback", "abstained"] = "extractive_fallback"
    fallback_reason: str | None = None
    index_version: str = "legal-index-v1"
    legal_timeline: list[dict] = Field(default_factory=list)


class CompareRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    applicable_date: date = Field(default_factory=date.today)
    domain: Domain | None = None
    pipelines: list[Pipeline] = ["L1", "L4"]


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, str]


class FeedbackRequest(BaseModel):
    rating: Literal["correct", "incorrect", "missing_evidence"]
    comment: str | None = Field(default=None, max_length=1000)


class DocumentIngestRequest(BaseModel):
    document_number: str = Field(min_length=2, max_length=100)
    title: str = Field(min_length=3, max_length=500)
    document_type: str = Field(min_length=2, max_length=100)
    issuing_authority: str = Field(min_length=2, max_length=200)
    issued_date: date
    effective_from: date
    effective_to: date | None = None
    domain: Domain
    source_url: str | None = None
    text: str = Field(min_length=20, max_length=2_000_000)
    publish: bool = False


class RelationRequest(BaseModel):
    source_document_id: UUID
    target_document_id: UUID
    relation_type: Literal["replaces", "amends", "supplements", "guides"]
    effective_from: date | None = None
    evidence_text: str | None = Field(default=None, max_length=2000)


class ProvisionEditRequest(BaseModel):
    content: str = Field(min_length=5, max_length=200_000)
    quality_flags: list[str] = Field(default_factory=list)
