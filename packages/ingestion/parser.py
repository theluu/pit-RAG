import re
import unicodedata
from dataclasses import dataclass


@dataclass
class ParsedProvision:
    chapter: str | None
    article: str
    clause: str | None
    point: str | None
    heading: str | None
    content: str


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text).lower()
    return re.sub(r"\s+", " ", text).strip()


# Tesseract confuses a couple of glyph shapes on scanned legal text, and both land in
# article headings: "Điều" comes back as "Điền" (u read as n) and "61" as "6l" (1 read
# as l). The first stopped the heading matching at all, so the article was swallowed
# into its predecessor; the second produced a citation pointing at an article number
# that does not exist. The keyword is matched loosely and the number is canonicalised,
# but the canonicaliser is the gate: anything it rejects is ordinary prose, so a line
# opening "Điều này..." falls through instead of starting an article.
#
# The separator after the number is required, not optional. A heading always closes the
# number with a full stop — 93 of 93 in that statute — while a cross-reference reads
# "Điều 36 của Luật này" with a space. Accepting both let a reference that OCR wrapped
# onto its own line open a bogus article, and every following line was then filed under
# the referenced number: text from Điều 24 was cited as Điều 1. A missed heading is
# visible; a mis-attributed one is a citation that looks right and points elsewhere.
_ARTICLE_HEAD = re.compile(r"^Đi[eêề][uùúủũụnr]\s+([0-9a-zđ|]+)\s*[.,:]\s*(.*)$", re.IGNORECASE)
_DIGIT_LOOKALIKES = str.maketrans({"l": "1", "L": "1", "I": "1", "|": "1"})

# Điểm run consecutively through the Vietnamese drafting alphabet (Nghị định 34/2016).
# The position in that run is what distinguishes "d)" from "đ)" when recognition cannot:
# a clause reading a, b, c, đ, đ, e has no điểm d and two điểm đ.
_POINT_SEQUENCE = "a b c d đ e g h i k l m n o p q r s t u v x y".split()
_POINT_CONFUSABLES = {"d": {"đ"}, "đ": {"d"}}


def _point_label(read: str, previous: str | None) -> str:
    """The điểm this marker must be, given the one before it in the same clause."""
    if previous is None or previous not in _POINT_SEQUENCE:
        return read
    index = _POINT_SEQUENCE.index(previous) + 1
    if index >= len(_POINT_SEQUENCE):
        return read
    expected = _POINT_SEQUENCE[index]
    return expected if read in _POINT_CONFUSABLES.get(expected, ()) else read


def _article_number(token: str) -> str | None:
    """Canonicalise an article number read off a scan, or None if it is not one.

    A trailing letter is kept: "Điều 3a" is a real heading for an inserted article. The
    digit lookalikes are translated first, so "6l" resolves to 61 rather than to article
    6 with an "l" suffix — no Vietnamese statute suffixes an article with l or i.
    """
    match = re.fullmatch(r"(\d+)([a-zđ]?)", token.translate(_DIGIT_LOOKALIKES), re.IGNORECASE)
    return match.group(1) + match.group(2).lower() if match else None


def parse_legal_text(text: str) -> list[ParsedProvision]:
    """Parse Vietnamese Chương/Điều/Khoản/Điểm while preserving legal boundaries."""
    chapter: str | None = None
    article: str | None = None
    heading: str | None = None
    clause: str | None = None
    point: str | None = None
    buffer: list[str] = []
    result: list[ParsedProvision] = []

    def flush() -> None:
        nonlocal buffer
        content = " ".join(x.strip() for x in buffer if x.strip()).strip()
        if article and content:
            result.append(ParsedProvision(chapter, article, clause, point, heading, content))
        buffer = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        head = _ARTICLE_HEAD.match(line)
        number = _article_number(head.group(1)) if head else None
        if re.match(r"^CHƯƠNG\s+[IVXLCDM0-9]+", line, re.IGNORECASE):
            flush()
            chapter = line
            clause = point = None
        elif number is not None:
            flush()
            article = number
            heading = head.group(2).strip(" .") or None
            clause = point = None
        elif article and (match := re.match(r"^(\d+)\.\s+(.+)$", line)):
            flush()
            clause = match.group(1)
            point = None
            buffer = [match.group(2)]
        elif article and (match := re.match(r"^([a-zđ])\)\s+(.+)$", line, re.IGNORECASE)):
            flush()
            point = _point_label(match.group(1).lower(), point)
            buffer = [match.group(2)]
        elif article:
            buffer.append(line)
    flush()
    return result
