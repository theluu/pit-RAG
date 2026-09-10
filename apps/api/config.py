from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    secret_key: str = "development-only-secret-change-me-32"
    access_token_minutes: int = 480
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    rate_limit_per_minute: int = 60
    database_url: str = "sqlite:///./legal_rag.db"
    redis_url: str = "redis://localhost:6379/0"
    neo4j_enabled: bool = False
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "legal_graph_password"
    neo4j_database: str = "neo4j"
    openai_api_key: str | None = None
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    enable_openai: bool = False
    openai_timeout_seconds: float = 12.0
    openai_circuit_seconds: int = 60
    openai_failure_threshold: int = 3
    max_upload_bytes: int = 10_000_000
    max_pdf_pages: int = 300
    object_store_endpoint: str = "localhost:9000"
    object_store_access_key: str = "minioadmin"
    object_store_secret_key: str = "minioadmin"
    object_store_bucket: str = "legal-documents"
    object_store_secure: bool = False
    ingestion_eager: bool = False
    ocr_enabled: bool = True
    ocr_min_chars_per_page: int = 80
    # A page whose imagery covers at least this much of it is treated as a scan, and
    # then only a genuinely full native layer keeps it out of OCR. Together these stop
    # a digital-signature stamp from passing a scanned page off as born-digital text.
    ocr_image_page_coverage: float = 0.5
    ocr_min_chars_over_image: int = 600
    ocr_dpi: int = 300
    ocr_language: str = "vie"
    ocr_min_confidence: float = 0.8
    ocr_psm: int = 3
    ocr_preprocess: bool = True
    ocr_min_tone_ratio: float = 0.05
    embedding_dimension: int = 1536
    embedding_batch_size: int = 64
    index_retention: int = 3
    ann_overfetch: int = 8
    hnsw_ef_search: int = 120
    clamav_host: str = "localhost"
    clamav_port: int = 3310
    malware_scan_required: bool = False
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
