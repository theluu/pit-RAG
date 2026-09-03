from apps.api.models import Citation, LegalDocument, RetrievedProvision


def generate(
    question: str, results: list[RetrievedProvision], documents: dict, level: str
) -> tuple[str, list[Citation], float, list[str]]:
    if level == "L0":
        return (
            "L0 không dùng kho tri thức. Bản demo chủ động không tạo câu trả lời pháp lý không có căn cứ.",
            [],
            0,
            ["Không có retrieval hoặc citation; không nên dùng cho quyết định pháp lý."],
        )
    if not results or max(x.rerank_score or x.fusion_score for x in results) < 0.03:
        return (
            "Chưa đủ căn cứ trong kho dữ liệu để trả lời câu hỏi này.",
            [],
            0.1,
            ["Không đủ căn cứ phù hợp; hãy bổ sung văn bản hoặc thu hẹp câu hỏi."],
        )
    selected = results[:2]
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
    confidence = min(0.96, 0.45 + max(c.score for c in citations))
    return "\n\n".join(sentences), citations, round(confidence, 2), []
