"""Regenerate the ingestion test fixtures.

Run with `python tests/fixtures/make_fixtures.py`. The PDFs are committed because the
base-14 PDF fonts cannot encode Vietnamese diacritics, so a fixture built on the fly would
extract as mojibake and never exercise the Điều/Khoản parser. Any Unicode TTF works; the
committed files were produced with Arial Unicode.
"""

from pathlib import Path

import fitz

FONT_CANDIDATES = [
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]
HERE = Path(__file__).parent

# Three pages, a repeating running header, and a clause that wraps across lines.
PAGES = [
    """CÔNG BÁO SỐ 12/2026
Chương I
QUY ĐỊNH CHUNG
Điều 1. Phạm vi điều chỉnh
1. Văn bản này quy định về thời giờ làm việc, thời giờ nghỉ ngơi của người lao động.
2. Người lao động được nghỉ hằng tuần ít nhất 24 giờ liên tục.""",
    """CÔNG BÁO SỐ 12/2026
Điều 2. Thời giờ làm thêm
1. Số giờ làm thêm của người lao động không quá 40 giờ trong 01 tháng và không quá
200 giờ trong 01 năm, trừ trường hợp quy định tại khoản 2 Điều này.
2. Người sử dụng lao động phải được sự đồng ý của người lao động.""",
    """CÔNG BÁO SỐ 12/2026
Điều 3. Hiệu lực thi hành
1. Văn bản này có hiệu lực thi hành kể từ ngày 01 tháng 02 năm 2026.""",
]


def find_font() -> str:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return path
    raise SystemExit("No Unicode TTF found; add one to FONT_CANDIDATES")


def build_born_digital(font_path: str) -> None:
    document = fitz.open()
    font = fitz.Font(fontfile=font_path)
    for body in PAGES:
        page = document.new_page()
        writer = fitz.TextWriter(page.rect)
        for offset, line in enumerate(body.splitlines()):
            writer.append((72, 80 + offset * 18), line, font=font, fontsize=11)
        writer.write_text(page)
    fitz.TOOLS.set_subset_fontnames(True)
    document.subset_fonts()
    document.save(HERE / "vietnamese_document.pdf", garbage=4, deflate=True)
    document.close()


def build_scanned() -> None:
    """Rasterise the born-digital file so no page has a text layer at all."""
    source = fitz.open(HERE / "vietnamese_document.pdf")
    output = fitz.open()
    for page in source:
        pixmap = page.get_pixmap(dpi=150)
        rendered = output.new_page(width=page.rect.width, height=page.rect.height)
        rendered.insert_image(rendered.rect, stream=pixmap.tobytes("png"))
    output.save(HERE / "scanned_document.pdf", garbage=4, deflate=True)
    output.close()
    source.close()


if __name__ == "__main__":
    build_born_digital(find_font())
    build_scanned()
    for name in ("vietnamese_document.pdf", "scanned_document.pdf"):
        document = fitz.open(HERE / name)
        print(f"{name}: {document.page_count} pages, "
              f"page 1 text layer = {len(document[0].get_text().strip())} chars")
        document.close()
