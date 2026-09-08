"""Ranking regressions for quantitative legal questions.

These reproduce a reported wrong answer: asked how many *hours* of weekly rest the law
requires, the engine returned the overtime *pay* rule ("200 phần trăm"). The numeric-answer
bonus fired for any number in any unit, and "giờ" was missing from the unit list entirely,
so the wrong provision collected +0.18 that the right one could not.
"""

from datetime import date
from uuid import UUID, uuid5

import pytest

from apps.api.models import LegalDocument, Provision
from packages.ingestion.parser import normalize
from packages.retrieval.engine import Retriever, expected_units, quantity_units

DOC = UUID("11111111-1111-1111-1111-111111111111")
TAX = UUID("22222222-2222-2222-2222-222222222222")
ON = date(2026, 6, 1)

CORPUS = [
    ("labor", "1", "2", "Người lao động được nghỉ hằng tuần ít nhất 24 giờ liên tục."),
    ("labor", "98", "1", "Vào ngày nghỉ hằng tuần, ít nhất bằng 200 phần trăm."),
    ("labor", "98", "2", ("Vào ngày nghỉ lễ, tết, ngày nghỉ có hưởng lương, ít nhất bằng "
                          "300 phần trăm chưa kể tiền lương ngày lễ.")),
    ("labor", "2", "1", "Số giờ làm thêm của người lao động không quá 40 giờ trong 01 tháng."),
    ("personal_income_tax", "1", "1",
     "Mức giảm trừ đối với đối tượng nộp thuế là 11 triệu đồng một tháng."),
    ("personal_income_tax", "1", "2",
     "Mức giảm trừ đối với mỗi người phụ thuộc là 4,4 triệu đồng một tháng."),
]


@pytest.fixture(scope="module")
def retriever():
    documents = [
        LegalDocument(id=DOC, document_number="45/2019/QH14", title="Bộ luật Lao động",
                      document_type="Luật", issuing_authority="Quốc hội",
                      issued_date=date(2019, 11, 20), effective_from=date(2021, 1, 1),
                      domain="labor", checksum="a" * 64),
        LegalDocument(id=TAX, document_number="954/2020/UBTVQH14", title="Nghị quyết giảm trừ",
                      document_type="Nghị quyết", issuing_authority="UBTVQH",
                      issued_date=date(2020, 6, 2), effective_from=date(2020, 7, 1),
                      domain="personal_income_tax", checksum="b" * 64),
    ]
    provisions = [
        Provision(id=uuid5(DOC if domain == "labor" else TAX, f"{article}-{clause}"),
                  document_id=DOC if domain == "labor" else TAX, article=article, clause=clause,
                  content=content, normalized_content=normalize(content))
        for domain, article, clause, content in CORPUS
    ]
    return Retriever(documents, provisions)


def top(retriever, question, domain):
    hits = retriever.search(question, ON, domain, "L4", 1)
    return hits[0].provision.content if hits else ""


@pytest.mark.parametrize("question", [
    "Người lao động được nghỉ hằng tuần ít nhất bao nhiêu giờ liên tục?",
    "Người lao động được nghỉ hằng tuần bao nhiêu giờ?",
    "Nghỉ hằng tuần bao nhiêu giờ?",
    # "mấy" and "bao lâu" are as common as "bao nhiêu" and must count as quantitative.
    "Mỗi tuần được nghỉ ít nhất mấy giờ?",
])
def test_hours_question_is_not_answered_with_a_percentage(retriever, question):
    assert "24 giờ liên tục" in top(retriever, question, "labor"), question


@pytest.mark.parametrize("question,expected", [
    ("Làm thêm ngày nghỉ hằng tuần được trả tối thiểu bao nhiêu phần trăm?", "200 phần trăm"),
    ("Làm thêm vào ngày lễ tết được trả bao nhiêu phần trăm?", "300 phần trăm"),
    ("Số giờ làm thêm tối đa trong 01 tháng là bao nhiêu?", "40 giờ"),
])
def test_percentage_and_hour_questions_still_reach_their_own_answers(retriever, question, expected):
    assert expected in top(retriever, question, "labor"), question


@pytest.mark.parametrize("question,expected", [
    # The law says "đối tượng nộp thuế" where people say "bản thân".
    ("Mức giảm trừ gia cảnh cho bản thân là bao nhiêu?", "11 triệu"),
    ("Mức giảm trừ cho mỗi người phụ thuộc là bao nhiêu?", "4,4 triệu"),
])
def test_taxpayer_and_dependant_allowances_are_not_confused(retriever, question, expected):
    assert expected in top(retriever, question, "personal_income_tax"), question


def test_expected_units_reads_the_unit_the_question_asks_for():
    # A question may name several units ("hằng tuần ... bao nhiêu giờ"); the ranker
    # intersects them with the units a candidate quantifies, so listing both is correct.
    units = expected_units(normalize("Nghỉ hằng tuần bao nhiêu giờ?"))
    assert "hour" in units and "week" in units
    assert "percent" in expected_units(normalize("Được trả bao nhiêu phần trăm?"))
    assert expected_units(normalize("Thủ tục đăng ký thế nào?")) == []


def test_quantity_units_only_counts_units_carrying_a_number():
    assert quantity_units("ít nhất 24 giờ liên tục") == {"hour"}
    assert quantity_units("ít nhất bằng 200 phần trăm") == {"percent"}
    # "giờ" with no number attached is not a quantified answer.
    assert quantity_units("thời giờ làm việc, thời giờ nghỉ ngơi") == set()


def test_seed_corpus_answers_weekly_rest_from_the_labour_code():
    """The demo corpus must contain Điều 111, not rely on an uploaded document.

    A test PDF was once published into the corpus and became the cited authority for this
    question, because the seed had no weekly-rest provision to answer it.
    """
    from apps.api.seed import load_seed

    documents, provisions = load_seed()
    code = next(d for d in documents if d.document_number == "45/2019/QH14")
    weekly = [p for p in provisions
              if p.document_id == code.id and "nghỉ ít nhất 24 giờ liên tục" in p.content]
    assert weekly, "45/2019/QH14 in the seed corpus is missing Điều 111"
    assert weekly[0].article == "111"
