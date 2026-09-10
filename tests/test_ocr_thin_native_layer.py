"""A thin native layer must not suppress OCR on a scanned page.

Reproduces silent content loss found on the dev deployment. Uploading Luật An toàn,
vệ sinh lao động (84/2015/QH13) produced 88 of its 93 articles: Điều 1, 2 and 3 were
missing entirely, and page 2 of the extraction began mid-sentence.

Page 1 of that PDF — like every Vietnamese công báo PDF signed by the Cổng Thông tin
điện tử Chính phủ — carries a digital-signature stamp as real embedded text:

    Ký bởi: Cổng Thông tin điện tử Chính phủ
    Email: thongtinchinhphu@chinhphu.vn
    Cơ quan: Văn phòng Chính phủ
    Thời gian ký: 16.07.2015 16:15:33 +07:00

That is ~120 printable characters, comfortably over ocr_min_chars_per_page (80), so
_needs_ocr said no and the page was accepted as "native". The body of the page — the
whole of Chương I — is a scanned image and was never read.

The character floor alone cannot separate the two cases. A page whose imagery covers
it has to be judged against that imagery, not against a fixed number of characters.
"""

import fitz
import pytest

from apps.api.config import settings
from packages.ingestion.pdf_pipeline import _needs_ocr

SIGNATURE = (
    "Ký bởi: Cổng Thông tin điện tử Chính phủ\n"
    "Email: thongtinchinhphu@chinhphu.vn\n"
    "Cơ quan: Văn phòng Chính phủ\n"
    "Thời gian ký: 16.07.2015 16:15:33 +07:00\n"
)
BODY = ("Điều 1. Phạm vi điều chỉnh. Luật này quy định việc bảo đảm an toàn, vệ sinh "
        "lao động; chính sách, chế độ đối với người bị tai nạn lao động. ") * 12


def page_with_image(coverage: float = 1.0) -> fitz.Page:
    """A page whose raster imagery covers the given fraction of its height."""
    doc = fitz.open()
    page = doc.new_page()
    pixmap = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 64, 64), False)
    pixmap.clear_with(200)
    rect = fitz.Rect(page.rect.x0, page.rect.y0, page.rect.x1,
                     page.rect.y0 + page.rect.height * coverage)
    page.insert_image(rect, pixmap=pixmap)
    return page


def blank_page() -> fitz.Page:
    return fitz.open().new_page()


def test_the_signature_stamp_on_a_scan_no_longer_suppresses_ocr():
    assert _printable(SIGNATURE) > settings.ocr_min_chars_per_page, (
        "the stamp must clear the character floor, or this test proves nothing"
    )
    assert _needs_ocr(page_with_image(), SIGNATURE) is True


def test_a_born_digital_text_page_is_left_alone():
    assert _needs_ocr(blank_page(), BODY) is False


def test_a_text_page_over_a_full_page_watermark_is_left_alone():
    """Letterhead and watermark backgrounds must not drag real text pages into OCR."""
    assert _needs_ocr(page_with_image(), BODY) is False


def test_an_image_page_with_no_text_at_all_still_needs_ocr():
    assert _needs_ocr(page_with_image(), "") is True


def test_a_thin_layer_without_any_imagery_still_needs_ocr():
    assert _needs_ocr(blank_page(), "trang 3") is True


def test_a_damaged_layer_needs_ocr_however_long_it_is():
    assert _needs_ocr(blank_page(), BODY[:400] + "�" * 40) is True


@pytest.mark.parametrize("page", [blank_page, lambda: page_with_image(0.2)])
def test_a_page_below_the_coverage_bar_is_judged_by_the_character_floor(page):
    """No imagery, or only a small illustration: the floor stays the only rule."""
    text = SIGNATURE  # over the floor, so the floor alone keeps it native
    assert _needs_ocr(page(), text) is False


def _printable(text: str) -> int:
    return sum(c.isprintable() and not c.isspace() for c in text)
