"""Two ways the parser attributed legal text to the wrong place.

Both found in the extraction of Luật An toàn, vệ sinh lao động (84/2015/QH13).

1. A cross-reference that OCR wrapped onto its own line was read as a heading.
   The article number in a heading is always followed by a full stop — 93 of 93 in
   that statute — while a reference reads "Điều 36 của Luật này." with a space. The
   optional `\\.?` in the old pattern accepted both, so six references opened bogus
   articles and every line after them was filed under the referenced number. Content
   from Điều 24 ended up cited as Điều 1.

   Mis-attribution is worse than a missed article: a missed one is visible, a
   mis-attributed one is a citation that looks right and points somewhere else.

2. "d)" was recognised as "đ)", which is also a valid Vietnamese point marker, so a
   clause ran a, b, c, đ, đ, e — two điểm đ and no điểm d. Points in Vietnamese
   drafting run consecutively, so the position in the sequence says which one was
   meant even when the glyph does not.
"""

import pytest

from packages.ingestion.parser import parse_legal_text


def parse(text: str):
    return parse_legal_text(text)


def labels(text: str):
    return [(p.article, p.clause, p.point) for p in parse(text)]


WRAPPED_REFERENCE = (
    "Điều 24. Bồi dưỡng bằng hiện vật\n"
    "1. Người lao động làm việc trong điều kiện có yếu tố nguy hiểm được bồi dưỡng\n"
    "bằng hiện vật theo quy định tại khoản 2\n"
    "Điều 36 của Luật này.\n"
    "2. Tổ chức thực hiện bồi dưỡng hiện vật theo quy định.\n"
)


def test_a_wrapped_cross_reference_does_not_open_an_article():
    assert {p.article for p in parse(WRAPPED_REFERENCE)} == {"24"}


def test_text_after_a_wrapped_reference_stays_with_its_own_article():
    parsed = parse(WRAPPED_REFERENCE)
    tail = [p for p in parsed if "bồi dưỡng hiện vật theo quy định" in p.content]
    assert tail and all(p.article == "24" for p in tail)


@pytest.mark.parametrize("line", [
    "Điều 36 của Luật này.",
    "Điều 45 và Điều 46 của Luật này; trả phí khám giám định.",
    "Điều 91 của Luật bảo hiểm xã hội;",
])
def test_reference_shapes_seen_in_the_corpus_are_not_headings(line):
    text = "Điều 7. Quyền của người sử dụng lao động\n1. Nội dung khoản một.\n" + line + "\n"
    assert {p.article for p in parse(text)} == {"7"}


def test_a_real_heading_is_still_a_heading():
    text = "Điều 36. Thống kê, báo cáo tai nạn lao động\n1. Nội dung khoản một.\n"
    assert [p.article for p in parse(text)] == ["36"]


POINTS = (
    "Điều 6. Quyền và nghĩa vụ của người lao động\n"
    "1. Người lao động có quyền sau đây:\n"
    "a) Được bảo đảm điều kiện làm việc an toàn;\n"
    "b) Được cung cấp thông tin đầy đủ;\n"
    "c) Được thực hiện chế độ bảo hộ lao động;\n"
    "đ) Yêu cầu bố trí công việc phù hợp sau khi điều trị;\n"
    "đ) Từ chối làm công việc nguy hiểm;\n"
    "e) Khiếu nại, tố cáo hoặc khởi kiện.\n"
)


def test_a_point_d_misread_as_dd_is_restored_from_its_position():
    points = [p.point for p in parse(POINTS) if p.point]
    assert points == ["a", "b", "c", "d", "đ", "e"]


def test_no_two_points_in_a_clause_share_a_label():
    labelled = [(p.clause, p.point) for p in parse(POINTS) if p.point]
    assert len(labelled) == len(set(labelled))


def test_a_genuine_dd_after_d_is_left_alone():
    text = (
        "Điều 9. Một điều khoản\n"
        "1. Nội dung mở đầu:\n"
        "c) Điểm c;\n"
        "d) Điểm d;\n"
        "đ) Điểm đ;\n"
    )
    assert [p.point for p in parse(text) if p.point] == ["c", "d", "đ"]


def test_points_restart_in_the_next_clause():
    text = (
        "Điều 10. Một điều khoản\n"
        "1. Khoản một:\n"
        "a) Điểm a của khoản một;\n"
        "2. Khoản hai:\n"
        "a) Điểm a của khoản hai;\n"
    )
    assert labels(text)[1:] == [("10", "1", "a"), ("10", "2", None), ("10", "2", "a")]
