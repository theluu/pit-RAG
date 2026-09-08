import dramatiq
from dramatiq.brokers.redis import RedisBroker

from apps.api.config import settings
from packages.ingestion.pdf_pipeline import (
    OCRQualityError,
    OCRUnavailableError,
    PDFValidationError,
)
from packages.ingestion.service import IngestionContentError, process_ingestion

dramatiq.set_broker(RedisBroker(url=settings.redis_url))

# A 300-page scan can spend several minutes in recognition; the 10-minute default would
# kill the actor mid-document and leave the job stuck in `extracting`.
INGESTION_TIME_LIMIT_MS = 60 * 60 * 1000

# Deterministic failures: the same bytes will fail identically every time. Retrying them
# just burns OCR time and inflates the attempt counter (one bad scan reached 33 attempts
# before this was classified), so dramatiq is told to fail them immediately. Transient
# faults — object store, database, embedding provider — still get the retry policy.
PERMANENT_FAILURES = (
    PDFValidationError,
    OCRQualityError,
    OCRUnavailableError,
    IngestionContentError,
)


@dramatiq.actor(max_retries=3, min_backoff=2_000, max_backoff=60_000,
                time_limit=INGESTION_TIME_LIMIT_MS, throws=PERMANENT_FAILURES)
def ingest_pdf(job_id: str) -> None:
    process_ingestion(job_id)
