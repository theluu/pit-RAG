# Architecture

The API owns authentication, retrieval orchestration, grounded generation and run records. Legal provisions are the smallest retrieval units; each keeps its document, chapter, article, clause and point identity. `Retriever` executes vector-style cosine and BM25 scoring, reciprocal-rank fusion and reranking. L2+ filters documents by domain and legal validity before scoring; L7 also surfaces excluded/replaced documents.

The offline deterministic implementation is intentional: demos and tests remain reproducible without credentials. Production adapters can replace sparse cosine with pgvector embeddings, the rule-based reranker with BGE, and extractive generation with an LLM while retaining the response contract and citation verifier.

PostgreSQL/pgvector and Redis are included in Compose as the production migration target. The current demo repository stores its curated seed corpus and run state in-process to keep first-run setup reliable; persistence adapters are the next milestone.
