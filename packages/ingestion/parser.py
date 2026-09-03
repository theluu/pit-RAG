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
        if re.match(r"^CHƯƠNG\s+[IVXLCDM0-9]+", line, re.IGNORECASE):
            flush()
            chapter = line
            clause = point = None
        elif match := re.match(r"^Điều\s+(\d+[a-zA-Z]?)\.?\s*(.*)$", line, re.IGNORECASE):
            flush()
            article = match.group(1)
            heading = match.group(2).strip(" .") or None
            clause = point = None
        elif article and (match := re.match(r"^(\d+)\.\s+(.+)$", line)):
            flush()
            clause = match.group(1)
            point = None
            buffer = [match.group(2)]
        elif article and (match := re.match(r"^([a-zđ])\)\s+(.+)$", line, re.IGNORECASE)):
            flush()
            point = match.group(1).lower()
            buffer = [match.group(2)]
        elif article:
            buffer.append(line)
    flush()
    return result
