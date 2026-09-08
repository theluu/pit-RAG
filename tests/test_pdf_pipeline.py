from pathlib import Path

import fitz
import pytest

from packages.ingestion.parser import parse_legal_text
from packages.ingestion.pdf_pipeline import (
    ExtractedPage,
    OCRUnavailableError,
    PageIndex,
    PDFValidationError,
    _reading_order,
    extract_pdf,
    validate_pdf,
)

FIXTURES = Path(__file__).parent / "fixtures"
# Three-page born-digital văn bản with a repeating "CÔNG BÁO" running header.
BORN_DIGITAL = (FIXTURES / "vietnamese_document.pdf").read_bytes()
# The same document rasterised: no text layer at all, so every page needs OCR.
SCANNED = (FIXTURES / "scanned_document.pdf").read_bytes()


def make_text_pdf(*pages: str) -> bytes:
    """ASCII-only helper; Vietnamese fixtures are files because base14 fonts cannot encode it."""
    document = fitz.open()
    for body in pages:
        page = document.new_page()
        for offset, line in enumerate(body.splitlines()):
            page.insert_text((72, 72 + offset * 14), line)
    data = document.tobytes()
    document.close()
    return data


def test_validate_rejects_spoofed_pdf():
    with pytest.raises(PDFValidationError):
        validate_pdf(b"not really a PDF")


def test_born_digital_pdf_uses_native_text():
    pages, warnings = extract_pdf(BORN_DIGITAL)
    assert len(pages) == 3
    assert all(page.extraction_method == "native" for page in pages)
    assert "Phạm vi điều chỉnh" in pages[0].text
    assert warnings == []


def test_born_digital_pdf_parses_into_provisions():
    pages, _ = extract_pdf(BORN_DIGITAL)
    parsed = parse_legal_text("\n".join(page.text for page in pages))
    assert [p.article for p in parsed] == ["1", "1", "2", "2", "3"]
    assert parsed[0].chapter and "Chương I" in parsed[0].chapter


def test_running_header_is_stripped_without_losing_article_headings():
    pages, _ = extract_pdf(BORN_DIGITAL)
    assert all("CÔNG BÁO" not in page.text for page in pages)
    assert all(all("CÔNG BÁO" not in block["text"] for block in page.blocks) for page in pages)
    # Page 3 is short enough that its head and tail windows overlap; the heading must survive.
    assert "Điều 3. Hiệu lực thi hành" in pages[2].text


def test_extract_reports_page_progress():
    seen = []
    extract_pdf(BORN_DIGITAL, on_page=lambda done, total: seen.append((done, total)))
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_scanned_pdf_routes_every_page_to_ocr(monkeypatch):
    """Rasterised pages have no text layer, so each one must be sent to recognition."""
    from packages.ingestion import pdf_pipeline

    recognised = []

    def fake_ocr(page):
        recognised.append(page.number + 1)
        return ExtractedPage(page.number + 1, f"Điều {page.number + 1}. Nội dung nhận dạng đầy đủ",
                             "ocr", 0.95, [])

    monkeypatch.setattr(pdf_pipeline, "_ocr_page", fake_ocr)
    pages, warnings = extract_pdf(SCANNED)
    assert recognised == [1, 2, 3]
    assert all(page.extraction_method == "ocr" for page in pages)
    assert warnings == []


def test_low_confidence_ocr_is_warned(monkeypatch):
    from packages.ingestion import pdf_pipeline

    monkeypatch.setattr(pdf_pipeline, "_ocr_page", lambda page: ExtractedPage(
        page.number + 1, "Điều 1. Nội dung nhận dạng kém chất lượng", "ocr", 0.42, []))
    _, warnings = extract_pdf(SCANNED)
    assert any("confidence thấp" in warning for warning in warnings)


def test_scanned_page_degrades_instead_of_failing_the_job(monkeypatch):
    """A page needing OCR without an engine must not abort a whole document."""
    monkeypatch.setattr("apps.api.config.settings.ocr_enabled", False)
    pages, warnings = extract_pdf(SCANNED)
    assert all(page.extraction_method == "native_degraded" for page in pages)
    assert len(warnings) == 3


def test_ocr_crash_on_one_page_keeps_the_rest(monkeypatch):
    from packages.ingestion import pdf_pipeline

    def flaky(page):
        if page.number == 1:
            raise MemoryError("recognition blew up")
        return ExtractedPage(page.number + 1, "Điều 9. Nội dung nhận dạng đầy đủ", "ocr", 0.9, [])

    monkeypatch.setattr(pdf_pipeline, "_ocr_page", flaky)
    pages, warnings = extract_pdf(SCANNED)
    assert [page.extraction_method for page in pages] == ["ocr", "native_degraded", "ocr"]
    assert any("MemoryError" in warning for warning in warnings)


def test_native_text_is_kept_when_ocr_recognises_less(monkeypatch):
    from packages.ingestion import pdf_pipeline

    monkeypatch.setattr("apps.api.config.settings.ocr_min_chars_per_page", 10_000)
    monkeypatch.setattr(pdf_pipeline, "_ocr_page", lambda page: ExtractedPage(
        page.number + 1, "rác", "ocr", 0.99, []))
    pages, warnings = extract_pdf(BORN_DIGITAL)
    assert all(page.extraction_method == "native" for page in pages)
    assert any("ít ký tự hơn" in warning for warning in warnings)


def fake_tesseract(languages, probes=None):
    module = type("pytesseract", (), {})
    module.Output = type("Output", (), {"DICT": "dict"})
    module.get_languages = lambda config="": (probes.append(1) if probes is not None else None) \
        or languages
    return module


def test_ocr_engine_is_probed_once(monkeypatch):
    import sys

    from packages.ingestion import pdf_pipeline

    pdf_pipeline._ocr_engine.cache_clear()
    probes = []
    monkeypatch.setitem(sys.modules, "pytesseract", fake_tesseract(["eng", "vie"], probes))
    try:
        assert pdf_pipeline._ocr_engine() is pdf_pipeline._ocr_engine()
        assert len(probes) == 1
    finally:
        pdf_pipeline._ocr_engine.cache_clear()


def test_ocr_engine_rejects_a_missing_language_pack(monkeypatch):
    """Without tesseract-ocr-vie the output would be silently tone-stripped."""
    import sys

    from packages.ingestion import pdf_pipeline

    pdf_pipeline._ocr_engine.cache_clear()
    monkeypatch.setitem(sys.modules, "pytesseract", fake_tesseract(["eng"]))
    with pytest.raises(OCRUnavailableError, match="vie"):
        pdf_pipeline._ocr_engine()
    pdf_pipeline._ocr_engine.cache_clear()


def test_ocr_engine_reports_missing_dependency(monkeypatch):
    import sys

    from packages.ingestion import pdf_pipeline

    pdf_pipeline._ocr_engine.cache_clear()
    monkeypatch.setitem(sys.modules, "pytesseract", None)
    with pytest.raises(OCRUnavailableError):
        pdf_pipeline._ocr_engine()
    pdf_pipeline._ocr_engine.cache_clear()


def test_tesseract_words_are_grouped_into_lines_with_confidence():
    from packages.ingestion.pdf_pipeline import _lines_from_words

    data = {
        "text": ["Điều", "1.", "", "Phạm", "rác"],
        "conf": ["96", "94", "-1", "90", "-1"],
        "left": [72, 110, 0, 72, 0], "top": [80, 80, 0, 100, 0],
        "width": [30, 12, 0, 40, 0], "height": [12, 12, 0, 12, 0],
        "block_num": [1, 1, 1, 1, 2], "par_num": [1, 1, 1, 1, 1],
        "line_num": [1, 1, 1, 2, 1],
    }
    blocks, confidences = _lines_from_words(data, 1.0)
    assert [b["text"] for b in blocks] == ["Điều 1.", "Phạm"]
    assert blocks[0]["bbox"] == [72, 80, 122, 92]
    assert round(confidences[0], 3) == 0.95


def test_tone_mark_ratio_separates_good_and_tone_stripped_text():
    from packages.ingestion.pdf_pipeline import tone_mark_ratio

    good = "Điều 1. Phạm vi điều chỉnh. Người lao động được nghỉ hằng tuần ít nhất 24 giờ."
    # Byte-for-byte what PaddleOCR's Latin charset returns for the same scan.
    stripped = "Điu 1. Phm vi điu chnh. Ngưi lao đng đưc ngh hng tưn ít nht 24 gi."
    assert tone_mark_ratio(good) > 0.2
    assert tone_mark_ratio(stripped) < 0.05
    # ă â ê ô ơ ư survive that charset, so counting every combining mark would blur the signal.
    assert tone_mark_ratio("Chương I. Văn bn ny") == 0.0


def test_tone_stripped_ocr_is_rejected(monkeypatch):
    """Publishing tone-stripped text as legal source would corrupt every citation."""
    from packages.ingestion import pdf_pipeline

    monkeypatch.setattr(pdf_pipeline, "_ocr_page", lambda page: ExtractedPage(
        page.number + 1,
        f"Điu {page.number + 1}. Phm vi điu chnh. Ngưi lao đng đưc ngh hng tưn 24 gi.",
        "ocr", 0.98, []))
    with pytest.raises(pdf_pipeline.OCRQualityError, match="mất dấu"):
        extract_pdf(SCANNED)


def test_correct_vietnamese_ocr_passes_the_charset_gate(monkeypatch):
    from packages.ingestion import pdf_pipeline

    monkeypatch.setattr(pdf_pipeline, "_ocr_page", lambda page: ExtractedPage(
        page.number + 1,
        f"Điều {page.number + 1}. Phạm vi điều chỉnh. Người lao động được nghỉ hằng tuần.",
        "ocr", 0.98, []))
    pages, _ = extract_pdf(SCANNED)
    assert all(page.extraction_method == "ocr" for page in pages)


def test_reading_order_sorts_columns_within_rows():
    blocks = [
        {"bbox": [300, 100, 400, 112], "text": "phai-tren"},
        {"bbox": [72, 200, 200, 212], "text": "trai-duoi"},
        {"bbox": [72, 101, 200, 113], "text": "trai-tren"},
    ]
    assert [b["text"] for b in _reading_order(blocks)] == ["trai-tren", "phai-tren", "trai-duoi"]


def _page(number, text, method="native", confidence=None):
    return ExtractedPage(number, text, method, confidence, [])


def test_provision_location_spans_pages():
    pages = [_page(1, "Điều 1. Người lao động được nghỉ"), _page(2, "hằng tuần ít nhất 24 giờ.")]
    location = PageIndex(pages).locate("Người lao động được nghỉ hằng tuần ít nhất 24 giờ.")
    assert (location.page_from, location.page_to) == (1, 2)
    assert "spans_pages" in location.quality_flags


def test_provision_location_marks_mixed_extraction_and_low_confidence():
    pages = [_page(1, "Điều 1. Phần đầu", "native"),
             _page(2, "phần cuối của điều khoản.", "ocr", 0.4)]
    location = PageIndex(pages).locate("Phần đầu phần cuối của điều khoản.")
    assert location.extraction_method == "mixed"
    assert location.confidence == 0.4
    assert "ocr_low_confidence" in location.quality_flags


def test_provision_location_flags_missing_provenance():
    location = PageIndex([_page(1, "Nội dung khác hẳn")]).locate("Không hề xuất hiện ở đâu")
    assert location.page_from is None
    assert "provenance_missing" in location.quality_flags


def test_provision_locations_are_resolved_across_a_real_document():
    pages, _ = extract_pdf(BORN_DIGITAL)
    index = PageIndex(pages)
    parsed = parse_legal_text("\n".join(page.text for page in pages))
    located = [index.locate(item.content) for item in parsed]
    assert all(location.page_from is not None for location in located)
    assert [location.page_from for location in located] == [1, 1, 2, 2, 3]
