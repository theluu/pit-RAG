from __future__ import annotations

from uuid import UUID, uuid5

from apps.api.config import settings
from apps.api.database import (
    ingestion_job_context,
    save_extracted_document,
    update_ingestion_job,
)
from apps.api.models import Provision
from packages.generation.openai_gateway import embed
from packages.ingestion.parser import normalize, parse_legal_text
from packages.ingestion.pdf_pipeline import PageIndex, extract_pdf
from packages.ingestion.storage import get_pdf

# Progress budget: extraction owns 15-55%, parsing 55-70%, embedding validation 70-95%.
EXTRACT_FLOOR, EXTRACT_CEILING = 15, 55


class IngestionContentError(ValueError):
    """The document's content cannot be ingested; retrying the same bytes cannot help."""


def process_ingestion(job_id: str) -> None:
    context = ingestion_job_context(job_id)
    if not context:
        raise ValueError("Unknown ingestion job")
    try:
        update_ingestion_job(job_id, "extracting", EXTRACT_FLOOR)

        def report(done: int, total: int) -> None:
            span = EXTRACT_CEILING - EXTRACT_FLOOR
            update_ingestion_job(job_id, "extracting",
                                 EXTRACT_FLOOR + int(span * done / max(total, 1)))

        pages, warnings = extract_pdf(get_pdf(context["object_key"]), on_page=report)
        if any(page.extraction_method in {"ocr", "native_degraded"} for page in pages):
            update_ingestion_job(job_id, "ocr", EXTRACT_CEILING, warnings=warnings)
        update_ingestion_job(job_id, "parsing", 65, warnings=warnings)
        parsed = parse_legal_text("\n".join(page.text for page in pages))
        if not parsed:
            raise IngestionContentError(
                "Không tách được cấu trúc Điều/Khoản. Với PDF scan, nguyên nhân thường là "
                "OCR đọc sai chữ 'Điều'; kiểm tra text trong tab preview.")
        document_id = UUID(context["document_id"])
        page_index = PageIndex(pages)
        provisions: list[Provision] = []
        for index, item in enumerate(parsed):
            location = page_index.locate(item.content)
            provisions.append(Provision(
                id=uuid5(document_id, f"{item.article}-{item.clause}-{item.point}-{index}"),
                document_id=document_id, chapter=item.chapter, article=item.article,
                clause=item.clause, point=item.point, heading=item.heading, content=item.content,
                normalized_content=normalize(item.content), page_from=location.page_from,
                page_to=location.page_to, extraction_method=location.extraction_method,
                extraction_confidence=location.confidence, quality_flags=location.quality_flags,
            ))
        warnings.extend(_quality_warnings(provisions))
        update_ingestion_job(job_id, "embedding", 70, warnings=warnings)
        if settings.enable_openai:
            # Validate that every chunk can be embedded before it is exposed for review/publish.
            for offset in range(0, len(provisions), settings.embedding_batch_size):
                batch = provisions[offset:offset + settings.embedding_batch_size]
                vectors = embed([p.normalized_content for p in batch])
                if vectors is None or any(len(v) != settings.embedding_dimension for v in vectors):
                    raise RuntimeError("Embedding provider returned an invalid batch")
                update_ingestion_job(job_id, "embedding", min(
                    95, 70 + int(25 * (offset + len(batch)) / max(len(provisions), 1))))
        else:
            warnings.append("Embedding chưa tạo: ENABLE_OPENAI=false; "
                            "publish sẽ dùng retrieval từ vựng thay cho pgvector index")
        save_extracted_document(job_id, [page.__dict__ for page in pages], provisions, warnings)
    except Exception as exc:
        update_ingestion_job(job_id, "failed", 100, error=str(exc))
        raise


def _quality_warnings(provisions: list[Provision]) -> list[str]:
    missing = [p for p in provisions if p.page_from is None]
    low = [p for p in provisions if "ocr_low_confidence" in p.quality_flags]
    degraded = [p for p in provisions if "ocr_unavailable" in p.quality_flags]
    warnings = []
    if missing:
        warnings.append(f"{len(missing)}/{len(provisions)} điều khoản không xác định được trang gốc")
    if low:
        warnings.append(f"{len(low)}/{len(provisions)} điều khoản có OCR confidence thấp")
    if degraded:
        warnings.append(f"{len(degraded)}/{len(provisions)} điều khoản thiếu OCR, cần review thủ công")
    return warnings
