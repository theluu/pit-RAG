from apps.api.models import Citation, LegalDocument, RetrievedProvision


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
    try:
        from openai import OpenAIError

        from packages.generation.openai_gateway import grounded_answer, verify_citations

        llm_result = grounded_answer(question, selected) if use_provider else None
        if llm_result and not llm_result["abstained"] and verify_citations(citations, results):
            sentences = [llm_result["answer"]]
            generation_mode = "openai"
        else:
            generation_mode = "extractive_fallback"
    except (OpenAIError, ValueError, RuntimeError):
        # Provider outages must never remove the deterministic, cited fallback.
        warnings = ["Không gọi được mô hình sinh; đang dùng câu trả lời trích xuất an toàn."]
        generation_mode = "extractive_fallback"
    else:
        warnings = []
    # Confidence rewards a strong best passage and independent supporting evidence,
    # while remaining deliberately conservative for legal answers.
    best = max(c.score for c in citations)
    support = min(c.score for c in citations) if len(citations) > 1 else 0
    confidence = min(0.96, 0.36 + best * 0.52 + support * 0.12)
    return "\n\n".join(sentences), citations, round(confidence, 2), warnings, generation_mode
