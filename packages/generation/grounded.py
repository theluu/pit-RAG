from apps.api.models import Citation, LegalDocument, RetrievedProvision

# Below this rerank score the top passage is, in practice, a topical near-miss rather
# than the provision that answers the question. Observed on the dev corpus: correct hits
# land at 0.88-1.25, while an out-of-corpus question topped out at 0.54.
WEAK_EVIDENCE_SCORE = 0.75


def generate(
    question: str, results: list[RetrievedProvision], documents: dict, level: str,
    use_provider: bool = True,
) -> tuple[str, list[Citation], float, list[str], str]:
    if level == "L0":
        return (
            "L0 không dùng kho tri thức. Bản demo chủ động không tạo câu trả lời pháp lý không có căn cứ.",
            [],
            0,
            ["Không có retrieval hoặc citation; không nên dùng cho quyết định pháp lý."],
            "abstained",
        )
    if not results or max(x.rerank_score or x.fusion_score for x in results) < 0.03:
        return (
            "Chưa đủ căn cứ trong kho dữ liệu để trả lời câu hỏi này.",
            [],
            0.1,
            ["Không đủ căn cứ phù hợp; hãy bổ sung văn bản hoặc thu hẹp câu hỏi."],
            "abstained",
        )
    # Prefer passages covering the same legal intent as the top hit. This avoids
    # adding a high-scoring but different sibling point (for example holiday pay
    # beside a question specifically about weekly-rest pay).
    def concepts(item: RetrievedProvision) -> set[str]:
        prefix = "Đúng ý định: "
        reason = next((x for x in item.match_reasons if x.startswith(prefix)), "")
        return {x.strip() for x in reason.removeprefix(prefix).split(",") if x.strip()}

    required = concepts(results[0])
    focused = [item for item in results if not required or concepts(item) >= required]
    candidates = focused or results
    numeric_question = any(term in question.lower() for term in ("bao nhiêu", "mức", "tỷ lệ"))
    if numeric_question and any(character.isdigit() for character in candidates[0].provision.content):
        selected = candidates[:1]
    else:
        selected = candidates[:2]
    citations = []
    sentences = []
    for item in selected:
        p = item.provision
        d: LegalDocument = documents[p.document_id]
        score = item.rerank_score or item.fusion_score
        citations.append(
            Citation(
                provision_id=p.id,
                document_id=d.id,
                document_number=d.document_number,
                title=d.title,
                article=p.article,
                clause=p.clause,
                point=p.point,
                quote=p.content[:420],
                source_url=d.source_url,
                score=round(score, 4),
            )
        )
        location = (
            f"Điều {p.article}"
            + (f" khoản {p.clause}" if p.clause else "")
            + (f" điểm {p.point}" if p.point else "")
        )
        sentences.append(f"Theo {location} {d.document_number}: {p.content}")
    warnings: list[str] = []
    generation_mode = "extractive_fallback"
    abstained = False
    try:
        from openai import OpenAIError

        from packages.generation.openai_gateway import grounded_answer, verify_citations

        llm_result = grounded_answer(question, selected) if use_provider else None
        if llm_result and llm_result["abstained"]:
            abstained = True
        elif llm_result and not verify_citations(citations, results):
            warnings = ["Câu trả lời của mô hình không khớp căn cứ; đang dùng trích xuất an toàn."]
        elif llm_result:
            sentences = [llm_result["answer"]]
            generation_mode = "openai"
    except (OpenAIError, ValueError, RuntimeError):
        # Provider outages must never remove the deterministic, cited fallback.
        warnings = ["Không gọi được mô hình sinh; đang dùng câu trả lời trích xuất an toàn."]
    if abstained:
        # The model read this evidence and judged it insufficient. Printing the retrieved
        # passages anyway turns a correct refusal into a confident off-topic answer, so
        # the abstention has to reach the caller intact.
        return (
            "Chưa đủ căn cứ trong kho dữ liệu để trả lời câu hỏi này.",
            [],
            0.1,
            ["Căn cứ truy hồi không trả lời được câu hỏi; hãy bổ sung văn bản hoặc thu hẹp câu hỏi."],
            "abstained",
        )
    # Confidence rewards a strong best passage and independent supporting evidence,
    # while remaining deliberately conservative for legal answers.
    best = max(c.score for c in citations)
    support = min(c.score for c in citations) if len(citations) > 1 else 0
    confidence = min(0.96, 0.36 + best * 0.52 + support * 0.12)
    if best < WEAK_EVIDENCE_SCORE:
        # The 0.36 floor let thin evidence report ~0.7, which reads as trustworthy.
        # Capping and warning is cheap when wrong; staying silent is not.
        confidence = min(confidence, 0.4)
        warnings = [*warnings, "Căn cứ truy hồi yếu; hãy kiểm chứng trực tiếp văn bản gốc."]
    return "\n\n".join(sentences), citations, round(confidence, 2), warnings, generation_mode
