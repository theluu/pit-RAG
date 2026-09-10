"""Abstention must survive the extractive fallback.

Reproduces a wrong answer found on the dev deployment: asked "Thủ tục đăng ký kết hôn?"
— nothing in the corpus covers marriage registration — the API answered with Điều 98 of
the Labour Code (overtime pay rates) at confidence 0.7 and an empty `warnings` list.

The generation gateway had abstained correctly, but `generate()` folded that signal into
the same branch as a failed citation check, then reset `warnings` to `[]` in the `else`
clause. A correct refusal became a confident off-topic answer, which for a legal lookup
is the worst possible outcome.
"""

from datetime import date
from uuid import UUID, uuid5

import pytest

from apps.api.models import LegalDocument, Provision, RetrievedProvision
from packages.generation import grounded
from packages.ingestion.parser import normalize

DOC = UUID("11111111-1111-1111-1111-111111111111")
OVERTIME = "Vào ngày nghỉ hằng tuần, ít nhất bằng 200 phần trăm."


@pytest.fixture
def evidence():
    document = LegalDocument(
        id=DOC, document_number="45/2019/QH14", title="Bộ luật Lao động 2019",
        document_type="Luật", issuing_authority="Quốc hội",
        issued_date=date(2019, 11, 20), effective_from=date(2021, 1, 1),
        domain="labor", checksum="a" * 64,
    )

    def hit(article: str, clause: str, content: str, score: float) -> RetrievedProvision:
        provision = Provision(
            id=uuid5(DOC, f"{article}-{clause}"), document_id=DOC, article=article,
            clause=clause, content=content, normalized_content=normalize(content),
        )
        return RetrievedProvision(provision=provision, fusion_score=score, rerank_score=score)

    return [hit("98", "1", OVERTIME, 0.54), hit("98", "2", "Ngày lễ 300 phần trăm.", 0.52)], {
        DOC: document
    }


def stub_gateway(monkeypatch, *, abstained: bool, verified: bool = True, answer: str = "Trả lời."):
    import packages.generation.openai_gateway as gw

    monkeypatch.setattr(
        gw, "grounded_answer",
        lambda question, selected: {
            "answer": answer, "claim_provision_ids": [], "abstained": abstained,
        },
    )
    monkeypatch.setattr(gw, "verify_citations", lambda citations, results: verified)


def test_llm_abstention_is_not_downgraded_into_an_answer(evidence, monkeypatch):
    results, documents = evidence
    stub_gateway(monkeypatch, abstained=True)

    answer, citations, confidence, warnings, mode = grounded.generate(
        "Thủ tục đăng ký kết hôn như thế nào?", results, documents, "L4",
    )

    assert mode == "abstained"
    assert OVERTIME not in answer
    assert citations == []
    assert confidence <= 0.1
    assert warnings, "an abstention must explain itself to the reader"


def test_failed_citation_verification_warns_instead_of_going_silent(evidence, monkeypatch):
    results, documents = evidence
    stub_gateway(monkeypatch, abstained=False, verified=False)

    _, _, _, warnings, mode = grounded.generate("Câu hỏi bất kỳ?", results, documents, "L4")

    assert mode == "extractive_fallback"
    assert warnings, "an unverified model answer must not fall back silently"


def test_verified_model_answer_is_used_and_stays_clean(evidence, monkeypatch):
    results, documents = evidence
    for item in results:  # strong evidence, so only fallback warnings could appear
        item.rerank_score = 1.05
    stub_gateway(monkeypatch, abstained=False, verified=True, answer="Ít nhất 200 phần trăm.")

    answer, citations, _, warnings, mode = grounded.generate(
        "Làm thêm ngày nghỉ hằng tuần trả bao nhiêu?", results, documents, "L4",
    )

    assert mode == "openai"
    assert answer == "Ít nhất 200 phần trăm."
    assert citations and warnings == []


def test_deterministic_path_without_a_provider_keeps_its_cited_fallback(evidence):
    results, documents = evidence

    answer, citations, _, _, mode = grounded.generate(
        "Làm thêm ngày nghỉ hằng tuần trả bao nhiêu?", results, documents, "L4",
        use_provider=False,
    )

    assert mode == "extractive_fallback"
    assert OVERTIME in answer and citations


def test_weak_evidence_cannot_report_moderate_confidence(evidence):
    """0.36 + best*0.52 gave thin evidence 0.7 — high enough to look trustworthy."""
    results, documents = evidence

    _, _, confidence, warnings, _ = grounded.generate(
        "Câu hỏi ngoài phạm vi kho dữ liệu?", results, documents, "L4", use_provider=False,
    )

    assert confidence <= 0.4, f"weak top score 0.54 still reported {confidence}"
    assert any("yếu" in w for w in warnings)


def test_strong_evidence_still_reports_high_confidence(evidence):
    results, documents = evidence
    for item in results:
        item.rerank_score = 1.05

    _, _, confidence, warnings, _ = grounded.generate(
        "Làm thêm ngày nghỉ hằng tuần trả bao nhiêu?", results, documents, "L4",
        use_provider=False,
    )

    assert confidence >= 0.9
    assert warnings == []
