"""Article headings must survive the glyph confusions OCR makes on scans.

Two headings in Luật An toàn, vệ sinh lao động (84/2015/QH13) came back from Tesseract
one character wrong, and the parser is strict about both positions:

    "Điền 55. Hỗ trợ chuyển đổi nghề nghiệp..."   u read as n, inside the keyword
    "Điều 6l. Giải quyết hưởng chế độ..."          1 read as l, inside the number

The first did not match ^Điều at all, so Điều 55 was swallowed into the body of Điều 54
and could never be cited. The second matched — `\\d+[a-zA-Z]?` accepts a trailing letter
for amended articles like "Điều 3a" — but recorded the article as "6l", so its citation
pointed at an article number that does not exist.

Neither confusion may be answered by loosening what counts as an article number: "Điều
3a" is a real heading and must keep its suffix.
"""

import pytest

from packages.ingestion.parser import parse_legal_text

BODY = "1. Người sử dụng lao động phải bố trí công việc phù hợp.\n"


def articles(text: str) -> list[str]:
    return [p.article for p in parse_legal_text(text)]


def test_the_keyword_read_with_n_for_u_is_still_an_article():
    text = "Điền 55. Hỗ trợ chuyển đổi nghề nghiệp cho người bị tai nạn lao động\n" + BODY
    assert articles(text) == ["55"]


def test_a_number_read_with_l_for_one_is_canonicalised():
    text = "Điều 6l. Giải quyết hưởng chế độ bảo hiểm tai nạn lao động\n" + BODY
    assert articles(text) == ["61"]


def test_the_two_confusions_together():
    text = "Điền 6l. Một điều khoản bị đọc sai cả hai chỗ\n" + BODY
    assert articles(text) == ["61"]


def test_a_misread_heading_does_not_swallow_the_previous_article():
    text = (
        "Điều 54. Dưỡng sức, phục hồi sức khỏe\n"
        "1. Người lao động được nghỉ dưỡng sức.\n"
        "Điền 55. Hỗ trợ chuyển đổi nghề nghiệp\n"
        "1. Người sử dụng lao động được hỗ trợ.\n"
    )
    parsed = parse_legal_text(text)
    assert [p.article for p in parsed] == ["54", "55"]
    assert "chuyển đổi nghề nghiệp" not in parsed[0].content


def test_an_amended_article_keeps_its_letter_suffix():
    text = "Điều 3a. Điều được bổ sung\n" + BODY
    assert articles(text) == ["3a"]


@pytest.mark.parametrize("heading", [
    "Điều 12. Quyền của người lao động",
    "ĐIỀU 12. Quyền của người lao động",
])
def test_correct_headings_are_unaffected(heading):
    assert articles(heading + "\n" + BODY) == ["12"]


def test_a_cross_reference_in_running_text_is_not_a_heading():
    """"quy định tại Điều 59" mid-sentence must not start a new article."""
    text = (
        "Điều 60. Giải quyết hưởng chế độ\n"
        "1. Trường hợp vượt quá thời hạn quy định tại Điều 59 của Luật này.\n"
    )
    assert articles(text) == ["60"]
