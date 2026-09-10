# Architecture

The API owns authentication, retrieval orchestration, grounded generation and run records. Legal provisions are the smallest retrieval units; each keeps its document, chapter, article, clause and point identity. `Retriever` executes vector-style cosine and BM25 scoring, reciprocal-rank fusion, intent coverage and reranking. L2+ filters documents by domain and legal validity before scoring; L7 also surfaces excluded/replaced documents.

## RAG strategy ladder

The levels are deliberately comparable rather than marketing aliases. Every response records
`retrieval_strategy`, `query_variants`, `execution_trace`, `retrieval_path` and `graph_path`.

| Level | Strategy | What changes | Purpose |
|---|---|---|---|
| L0 | No retrieval | Abstains without evidence | Negative control / hallucination baseline |
| L1 | Dense baseline | pgvector cosine in production; explicitly flagged sparse fallback locally | Measures semantic retrieval alone |
| L2 | Metadata-filtered | L1 plus domain and effective-date eligibility | Tests pre-filtering correctness |
| L3 | Hybrid RAG | ANN + PostgreSQL FTS, fused with RRF | Improves exact legal terms and semantic recall |
| L4 | Reranked RAG | Hybrid candidates plus legal concept, reference, and unit-aware reranking | Improves top-k precision |
| L5 | GraphRAG | L4 seeds → Neo4j legal neighborhood → graph-aware reranking | Surfaces amendment/replacement context |
| L6 | Multi-query RAG | Auditable Vietnamese rewrites → per-query L4 retrieval → RRF aggregation | Improves recall across user phrasing |
| L7 | Adaptive RAG | Multi-query + hybrid + graph expansion + temporal guard | Production-oriented orchestration |

Graph edges never become legal evidence by themselves. They alter discovery/ranking and provide
a legal timeline; the final answer may cite only stored provisions. PostgreSQL remains the source
of truth, while Neo4j is an idempotent projection with a visible SQL fallback.

Evaluation reports citation precision/recall, retrieval hit-rate, mean reciprocal rank,
abstention rate and p50/p95 latency. The same cases run against each strategy so improvements and
trade-offs are reproducible.

SQLAlchemy persists curated documents, page provenance, ingestion jobs, index versions, identities, runs, feedback and audit events. PDF bytes and artifacts live in MinIO. Redis/Dramatiq drives a separate OCR worker. Curators review extracted pages and legal chunks before publishing. The optional OpenAI gateway uses structured Responses output, validates returned provision IDs, and keeps deterministic generation as a fail-safe.

## PDF ingestion and OCR

Upload validates the signature, page count and size, scans for malware, stores the bytes in MinIO and enqueues a Dramatiq job. The worker then, per page:

1. reads the embedded text layer (`get_text("blocks", sort=True)`) and re-sorts blocks into reading order, because the parser depends on Điều/Khoản arriving in sequence;
2. sends the page to Tesseract only when the native layer is thin (`OCR_MIN_CHARS_PER_PAGE`) or full of replacement characters — a born-digital file is never rasterised;
3. renders at `OCR_DPI`, then grayscales, equalises and deskews before recognition, and maps recognised boxes back to PDF points so OCR and native provenance share one coordinate space;
4. keeps whichever text is richer when a hybrid page yields both.

A page that OCR cannot handle degrades to `native_degraded` with a warning rather than failing the document, and running headers are stripped per line so a short page cannot lose a genuine Điều heading.

### Why Tesseract, not PaddleOCR

PaddleOCR classifies `vi` as a Latin language, and its Latin recognition dictionary (836 characters) carries the Vietnamese base vowels — ă â ê ô ơ ư đ — but **none of the tone-marked ones**. It therefore deletes every tone from its output while reporting >0.95 confidence: `Điều 1. Phạm vi điều chỉnh` comes back as `Điu 1. Phm vi điu chnh`. No configuration fixes this, because `lang="vi"` resolves to that same dictionary and there is no Vietnamese model in PaddleOCR 3.7. Tesseract's `vie` traineddata reproduces the same scan exactly.

Because the failure is silent and high-confidence, the pipeline also measures it directly. `tone_mark_ratio` counts the five Vietnamese tone codepoints (huyền, sắc, ngã, hỏi, nặng) per letter — deliberately excluding the vowel-shape marks a Latin charset does carry. Correct prose scores ~0.22; tone-stripped output scores ~0.02. Anything under `OCR_MIN_TONE_RATIO` raises `OCRQualityError` and fails the job with an actionable message, so corrupted text can never reach a citation.

Deterministic failures — an invalid PDF, a tone-stripped scan, an unparseable structure — are listed in the worker's `throws` set so Dramatiq fails them immediately. Before that classification one bad scan reached 33 attempts, re-running OCR each time.

After parsing, `PageIndex` maps offsets in the concatenated page text back to page numbers, giving each provision a `page_from`/`page_to` span, an extraction method, a confidence and quality flags (`ocr_low_confidence`, `ocr_unavailable`, `spans_pages`, `provenance_missing`). Progress is written to the job at every stage, so the review UI tracks a long scan instead of showing "queued". Every chunk is test-embedded before the document reaches review, so a publish cannot fail halfway.

## Ranking quantitative questions

Vietnamese legal answers are usually a number with a unit, and the unit is the whole answer:
"nghỉ hằng tuần ít nhất 24 **giờ**" and "trả ít nhất 200 **phần trăm**" are different rules in
neighbouring articles. The reranker therefore reads the unit out of the question
(`expected_units`) and only rewards a candidate that quantifies *that* unit
(`quantity_units`). An earlier version rewarded any number in any unit and omitted "giờ"
from its unit list entirely, so "bao nhiêu giờ" was answered with a percentage — the bonus
alone was larger than the keyword margin between the two provisions.

`CONCEPTS` is the auditable synonym layer for the gap between how the law is written and how
people ask: the statute says "đối tượng nộp thuế" where a user says "bản thân", and states
the weekly-rest rule as "được nghỉ hằng tuần" while the overtime-pay rule says "vào ngày nghỉ
hằng tuần". `tests/test_ranking.py` pins these cases.

## Provider circuit breakers

Chat and embeddings get separate breakers, and each opens only after
`OPENAI_FAILURE_THRESHOLD` consecutive failures. Both properties matter: with one shared
breaker that tripped on the first error, a single slow generation call disabled embeddings
for `OPENAI_CIRCUIT_SECONDS`, which dropped retrieval to the lexical path — so a transient
timeout on the *generation* endpoint quietly changed which provisions were *retrieved*. The
timeout default is 12s against a measured p50 of ~1.3s and p100 of ~2.3s for gpt-4o-mini
with structured output; the previous 3s left almost no headroom.

## Production vector index

Publishing embeds all published provisions into a new, inactive `index_versions` row plus its `provision_index_entries`. Activation is transactional and exclusive: the predecessor becomes `retired` and stays reactivatable for rollback, activation refuses a dimension that no longer matches `EMBEDDING_DIMENSION`, and entries beyond `INDEX_RETENTION` are pruned.

Retrieval resolves the active version, then runs two arms that both order before they truncate:

- **ANN** — over-fetches `ANN_OVERFETCH × k` from `provision_index_entries` filtered only by `index_version_id`, so PostgreSQL can use the HNSW index. Joining `index_versions` or pre-filtering by document metadata there defeats the index and silently degrades into sorting the whole corpus. `hnsw.ef_search` is raised to match the over-fetch and `hnsw.iterative_scan` covers the post-filter where pgvector supports it.
- **Full text** — `ts_rank_cd` over the GIN index on `search_text`.

Eligibility (published, domain, effective date) is applied to both arms afterwards, and the union feeds RRF and the auditable legal reranker. Offline SQLite tests use deterministic sparse scoring; `tests/test_pgvector_index.py` covers the SQL that only PostgreSQL can run. If the embedding provider is unavailable, retrieval falls back to the lexical path, marks the run `lexical_fallback` and warns rather than failing.
