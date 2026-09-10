from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

import fitz

from apps.api.config import settings


@dataclass
class ExtractedPage:
    page_number: int
    text: str
    extraction_method: str
    confidence: float | None
    blocks: list[dict]


@dataclass
class ProvisionLocation:
    page_from: int | None
    page_to: int | None
    extraction_method: str
    confidence: float | None
    quality_flags: list[str] = field(default_factory=list)


class PDFValidationError(ValueError):
    pass


class OCRUnavailableError(RuntimeError):
    """OCR was required for a page but the engine could not be used."""


class OCRQualityError(ValueError):
    """Recognition returned text whose Vietnamese tone marks were lost.

    A recognition model without the full Vietnamese charset silently deletes every
    tone-carrying vowel ("Điều" -> "Điu", "nghỉ hằng tuần" -> "ngh hng tưn") while still
    reporting >0.95 confidence. The text is unusable as legal source material and the
    Điều/Khoản parser cannot match it, so it must be rejected loudly rather than retried
    or published.
    """


def validate_pdf(data: bytes) -> int:
    if not data.startswith(b"%PDF-"):
        raise PDFValidationError("File signature is not PDF")
    if len(data) > settings.max_upload_bytes:
        raise PDFValidationError(f"PDF exceeds {settings.max_upload_bytes} bytes")
    try:
        document = fitz.open(stream=data, filetype="pdf")
        pages = document.page_count
        encrypted = document.needs_pass
        document.close()
    except Exception as exc:
        raise PDFValidationError("PDF is corrupt or encrypted") from exc
    if encrypted:
        raise PDFValidationError("PDF is password protected")
    if pages < 1 or pages > settings.max_pdf_pages:
        raise PDFValidationError(f"PDF must contain 1-{settings.max_pdf_pages} pages")
    return pages


def _reading_order(blocks: list[dict]) -> list[dict]:
    """Sort blocks top-to-bottom then left-to-right.

    Detection output (and, for damaged files, native output) is not guaranteed to be in
    reading order, and the parser downstream depends on Điều/Khoản arriving in sequence.
    Blocks whose vertical centres are within one line height are treated as the same row.
    """
    if not blocks:
        return []
    heights = [b["bbox"][3] - b["bbox"][1] for b in blocks if len(b.get("bbox") or []) == 4]
    tolerance = max(4.0, (sum(heights) / len(heights)) * 0.6) if heights else 8.0

    def key(block: dict) -> tuple[float, float]:
        bbox = block.get("bbox") or [0, 0, 0, 0]
        if len(bbox) != 4:
            return (0.0, 0.0)
        centre = (bbox[1] + bbox[3]) / 2
        return (round(centre / tolerance), bbox[0])

    return sorted(blocks, key=key)


def _native_page(page: fitz.Page) -> ExtractedPage:
    raw_blocks = page.get_text("blocks", sort=True)
    blocks = [{"bbox": [b[0], b[1], b[2], b[3]], "text": b[4].strip()}
              for b in raw_blocks if b[4].strip()]
    blocks = _reading_order(blocks)
    text = "\n".join(block["text"] for block in blocks)
    return ExtractedPage(page.number + 1, text, "native", None, blocks)


# The five Vietnamese tones as combining codepoints: huyền, sắc, ngã, hỏi, nặng. Deliberately
# excludes the vowel-shape marks (circumflex, breve, horn) that produce ă â ê ô ơ ư — a Latin
# recognition charset carries those, so counting them would blur the very signal we need.
TONE_MARKS = frozenset("\u0300\u0301\u0303\u0309\u0323")


def tone_mark_ratio(text: str) -> float:
    """Vietnamese tone marks per letter.

    Correct legal prose scores around 0.2-0.3; text from a recognition charset without the
    tone-marked vowels scores near zero, because those characters are dropped outright.
    """
    letters = sum(char.isalpha() for char in text)
    if not letters:
        return 0.0
    decomposed = unicodedata.normalize("NFD", text)
    return sum(char in TONE_MARKS for char in decomposed) / letters


def _printable_chars(text: str) -> int:
    return sum(char.isprintable() and not char.isspace() for char in text)


def _image_coverage(page: fitz.Page) -> float:
    """Fraction of the page covered by raster imagery, clamped to 1."""
    page_area = abs(page.rect.get_area())
    if not page_area:
        return 0.0
    covered = 0.0
    for info in page.get_image_info():
        bbox = fitz.Rect(info["bbox"]) & page.rect
        if not bbox.is_empty:
            covered += abs(bbox.get_area())
    return min(covered / page_area, 1.0)


def _needs_ocr(page: fitz.Page, text: str) -> bool:
    replacement_ratio = text.count("�") / max(1, len(text))
    if replacement_ratio > 0.02:
        return True
    chars = _printable_chars(text)
    if chars < settings.ocr_min_chars_per_page:
        return True
    # A scanned page can carry a thin native layer of its own. Every Vietnamese công
    # báo PDF stamps page 1 with a digital signature — around 120 characters, well over
    # the floor above — while the entire body of that page stays an unread image. The
    # floor cannot tell that page from a real one, so a page covered by its own imagery
    # is judged against the imagery instead.
    return (
        _image_coverage(page) >= settings.ocr_image_page_coverage
        and chars < settings.ocr_min_chars_over_image
    )


@lru_cache(maxsize=1)
def _ocr_engine():
    """Resolve the Tesseract binary and confirm the language data is installed.

    Tesseract is used rather than PaddleOCR because PaddleOCR classifies `vi` as a Latin
    language, and its Latin recognition dictionary contains the Vietnamese base vowels
    (ă â ê ô ơ ư đ) but none of the tone-marked ones. It therefore deletes every tone from
    the output at >0.95 reported confidence — "Điều" comes back as "Điu" — which no
    configuration can fix. Tesseract's `vie` model reproduces the text exactly.

    Cached because the availability probe shells out; recognition itself is stateless.
    """
    try:
        import pytesseract
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise OCRUnavailableError(
            "Install the 'ocr' optional dependencies to process scanned PDFs"
        ) from exc
    try:
        installed = pytesseract.get_languages(config="")
    except Exception as exc:  # missing binary surfaces as several exception types
        raise OCRUnavailableError(f"Tesseract is not usable: {exc}") from exc
    if settings.ocr_language not in installed:
        raise OCRUnavailableError(
            f"Tesseract language '{settings.ocr_language}' is not installed "
            f"(available: {', '.join(sorted(installed))}); add tesseract-ocr-"
            f"{settings.ocr_language}"
        )
    return pytesseract


def _preprocess(image, cv2, np):
    """Grayscale, deskew and equalise a rendered page before recognition."""
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    grey = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(grey)
    binary = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    coords = cv2.findNonZero(binary)
    angle = 0.0
    if coords is not None and len(coords) > 50:
        angle = cv2.minAreaRect(coords)[-1]
        angle = angle + 90 if angle < -45 else angle
    if abs(angle) > 0.3:
        height, width = grey.shape
        matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
        grey = cv2.warpAffine(grey, matrix, (width, height),
                              flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return cv2.cvtColor(grey, cv2.COLOR_GRAY2BGR)


def _lines_from_words(data: dict, scale: float) -> tuple[list[dict], list[float]]:
    """Group Tesseract's per-word output into lines with a box and a mean confidence."""
    grouped: dict[tuple, list[int]] = {}
    for index, text in enumerate(data["text"]):
        if not text.strip() or float(data["conf"][index]) < 0:
            continue
        key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
        grouped.setdefault(key, []).append(index)
    blocks: list[dict] = []
    confidences: list[float] = []
    for indexes in grouped.values():
        words = [data["text"][i].strip() for i in indexes]
        scores = [float(data["conf"][i]) / 100.0 for i in indexes]
        left = min(data["left"][i] for i in indexes)
        top = min(data["top"][i] for i in indexes)
        right = max(data["left"][i] + data["width"][i] for i in indexes)
        bottom = max(data["top"][i] + data["height"][i] for i in indexes)
        confidence = sum(scores) / len(scores)
        blocks.append({
            "bbox": [round(v * scale, 2) for v in (left, top, right, bottom)],
            "text": " ".join(words), "confidence": round(confidence, 4),
        })
        confidences.append(confidence)
    return blocks, confidences


def _ocr_page(page: fitz.Page) -> ExtractedPage:
    if not settings.ocr_enabled:
        raise OCRUnavailableError("OCR is required for this page but OCR is disabled")
    try:
        import cv2
        import numpy as np
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise OCRUnavailableError(
            "Install the 'ocr' optional dependencies to process scanned PDFs"
        ) from exc
    pytesseract = _ocr_engine()
    pixmap = page.get_pixmap(dpi=settings.ocr_dpi, alpha=False)
    image = cv2.imdecode(np.frombuffer(pixmap.tobytes("png"), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise OCRUnavailableError("Rendered page could not be decoded for OCR")
    if settings.ocr_preprocess:
        image = _preprocess(image, cv2, np)
    data = pytesseract.image_to_data(
        image, lang=settings.ocr_language, config=f"--psm {settings.ocr_psm}",
        output_type=pytesseract.Output.DICT,
    )
    # Boxes come back in render pixels; rescale to PDF points so OCR and native
    # provenance share one coordinate space.
    blocks, confidences = _lines_from_words(data, 72.0 / settings.ocr_dpi)
    blocks = _reading_order(blocks)
    text = "\n".join(block["text"] for block in blocks)
    confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return ExtractedPage(page.number + 1, text, "ocr", confidence, blocks)


def _extract_page(page: fitz.Page, warnings: list[str]) -> ExtractedPage:
    """Native text first, OCR only when the native layer is thin or damaged.

    A failure of the OCR engine degrades a single page instead of aborting the job: the
    native text is kept and the page is marked so review can catch it.
    """
    native = _native_page(page)
    if not _needs_ocr(page, native.text):
        return native
    try:
        scanned = _ocr_page(page)
    except OCRUnavailableError as exc:
        warnings.append(f"Trang {native.page_number}: OCR không chạy được ({exc})")
        native.extraction_method = "native_degraded"
        return native
    except Exception as exc:  # noqa: BLE001 - one bad page must not lose the document
        warnings.append(f"Trang {native.page_number}: OCR lỗi ({type(exc).__name__})")
        native.extraction_method = "native_degraded"
        return native
    if _printable_chars(scanned.text) < _printable_chars(native.text):
        # A hybrid page whose embedded layer already beat recognition; keep the better text.
        warnings.append(f"Trang {native.page_number}: giữ text gốc vì OCR cho ít ký tự hơn")
        return native
    if scanned.confidence is not None and scanned.confidence < settings.ocr_min_confidence:
        warnings.append(f"Trang {scanned.page_number}: OCR confidence thấp "
                        f"({scanned.confidence:.2f})")
    return scanned


def _remove_repeating_headers(pages: list[ExtractedPage]) -> None:
    if len(pages) < 3:
        return
    candidates: dict[str, int] = {}
    for page in pages:
        lines = [line.strip() for line in page.text.splitlines() if line.strip()]
        # Count each line once per page: on a short page the head and tail windows overlap,
        # and double counting there is enough to delete a genuine Điều heading.
        seen = {re.sub(r"\d+", "#", line.casefold()) for line in lines[:2] + lines[-2:]}
        for key in seen:
            candidates[key] = candidates.get(key, 0) + 1
    repeated = {key for key, count in candidates.items() if count / len(pages) >= 0.6}
    def strip(body: str) -> str:
        return "\n".join(line for line in body.splitlines()
                         if re.sub(r"\d+", "#", line.strip().casefold()) not in repeated)

    for page in pages:
        page.text = strip(page.text)
        # A native block can hold several lines, so filter inside blocks too and drop the
        # ones that were nothing but the running header.
        rebuilt = []
        for block in page.blocks:
            body = strip(block["text"])
            if body.strip():
                rebuilt.append({**block, "text": body})
        page.blocks = rebuilt


def extract_pdf(
    data: bytes, on_page: Callable[[int, int], None] | None = None
) -> tuple[list[ExtractedPage], list[str]]:
    """Extract every page, reporting progress so long scans do not look stalled."""
    validate_pdf(data)
    document = fitz.open(stream=data, filetype="pdf")
    pages: list[ExtractedPage] = []
    warnings: list[str] = []
    try:
        total = document.page_count
        for page in document:
            pages.append(_extract_page(page, warnings))
            if on_page:
                on_page(page.number + 1, total)
    finally:
        document.close()
    # Charset check first: it judges raw recognition output, and header stripping can
    # legitimately empty a page and hide the evidence.
    _assert_ocr_charset(pages)
    _remove_repeating_headers(pages)
    return pages, warnings


def _assert_ocr_charset(pages: list[ExtractedPage]) -> None:
    """Reject recognition output that lost its Vietnamese tone marks.

    Checked per document rather than per page: a single short page can legitimately be
    tone-poor, a whole scanned văn bản cannot.
    """
    recognised = [page for page in pages if page.extraction_method == "ocr"]
    body = " ".join(page.text for page in recognised)
    if len(body) < settings.ocr_min_chars_per_page or not recognised:
        return
    ratio = tone_mark_ratio(body)
    if ratio < settings.ocr_min_tone_ratio:
        raise OCRQualityError(
            f"OCR trả về text mất dấu thanh tiếng Việt (tỷ lệ {ratio:.3f} < "
            f"{settings.ocr_min_tone_ratio}). Bộ ký tự của model nhận dạng "
            f"'{settings.ocr_language}' không đủ cho tiếng Việt — cài đúng gói ngôn ngữ "
            f"(tesseract-ocr-vie) rồi ingest lại."
        )


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


class PageIndex:
    """Maps offsets in the concatenated page text back to page numbers.

    The parser sees one joined string, so a provision that starts on page 4 and ends on
    page 5 must resolve to that span rather than to a single page.
    """

    def __init__(self, pages: list[ExtractedPage]):
        self.pages = pages
        self._spans: list[tuple[int, int, ExtractedPage]] = []
        parts: list[str] = []
        cursor = 0
        for page in pages:
            body = _collapse(page.text)
            self._spans.append((cursor, cursor + len(body), page))
            parts.append(body)
            cursor += len(body) + 1
        self.text = " ".join(parts)

    def _page_at(self, offset: int) -> ExtractedPage | None:
        for start, end, page in self._spans:
            if start <= offset <= end:
                return page
        return self._spans[-1][2] if self._spans else None

    def locate(self, content: str) -> ProvisionLocation:
        needle = _collapse(content)
        if not needle or not self.text:
            return ProvisionLocation(None, None, "mixed", None, ["provenance_missing"])
        start = self.text.find(needle)
        end = start + len(needle) if start >= 0 else -1
        if start < 0:
            head = needle[:80]
            start = self.text.find(head) if head else -1
            end = start + len(head) if start >= 0 else -1
        if start < 0:
            return ProvisionLocation(None, None, "mixed", None, ["provenance_missing"])
        first, last = self._page_at(start), self._page_at(max(start, end - 1))
        if first is None or last is None:
            return ProvisionLocation(None, None, "mixed", None, ["provenance_missing"])
        span = [p for p in self.pages if first.page_number <= p.page_number <= last.page_number]
        methods = {p.extraction_method for p in span}
        method = methods.pop() if len(methods) == 1 else "mixed"
        if method == "native_degraded":
            method = "native"
        scores = [p.confidence for p in span if p.confidence is not None]
        confidence = min(scores) if scores else None
        flags = []
        if confidence is not None and confidence < settings.ocr_min_confidence:
            flags.append("ocr_low_confidence")
        if any(p.extraction_method == "native_degraded" for p in span):
            flags.append("ocr_unavailable")
        if last.page_number > first.page_number:
            flags.append("spans_pages")
        return ProvisionLocation(first.page_number, last.page_number, method, confidence, flags)


def locate_provision(content: str, pages: list[ExtractedPage]) -> ProvisionLocation:
    return PageIndex(pages).locate(content)
