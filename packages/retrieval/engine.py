import math
import re
from collections import Counter
from datetime import date

from apps.api.models import LegalDocument, Provision, RetrievedProvision
from packages.ingestion.parser import normalize

STOP = {"là", "và", "có", "được", "theo", "cho", "của", "với", "một", "những", "gì", "bao", "nhiêu"}

# Small, auditable legal vocabulary instead of opaque query rewriting.  Each group
# represents concepts that people commonly phrase differently in Vietnamese.
CONCEPTS = {
    "overtime": {"làm thêm", "tăng ca", "ngoài giờ"},
    # The rest-duration rule is phrased "được nghỉ hằng tuần", without "ngày"; requiring the
    # prefix matched only the overtime-pay article and missed the provision being asked about.
    "weekly_rest": {"nghỉ hằng tuần", "nghỉ hàng tuần", "cuối tuần"},
    "probation": {"thử việc", "thời gian thử việc"},
    "retirement": {"lương hưu", "hưu trí", "nghỉ hưu"},
    "social_insurance": {"bảo hiểm xã hội", "bhxh"},
    "family_deduction": {"giảm trừ gia cảnh", "người phụ thuộc"},
    # The taxpayer's own allowance and the per-dependant allowance are different numbers in
    # the same điều. The law says "đối tượng nộp thuế" where people say "bản thân".
    "taxpayer_self": {"bản thân", "người nộp thuế", "đối tượng nộp thuế"},
    "dependant": {"người phụ thuộc"},
}


def tokens(text: str) -> list[str]:
    return [x for x in re.findall(r"\w+", normalize(text)) if len(x) > 1 and x not in STOP]


# Units a quantitative legal answer is expressed in. Grouped so that a question asking
# "bao nhiêu giờ" is satisfied by "24 giờ" but not by "200 phần trăm".
UNITS = {
    "percent": ("%", "phần trăm"),
    "hour": ("giờ",),
    "day": ("ngày",),
    "week": ("tuần",),
    "month": ("tháng",),
    "year": ("năm",),
    "money": ("đồng", "triệu", "tỷ"),
    "times": ("lần",),
    "person": ("người",),
}


def expected_units(normalized: str) -> list[str]:
    """Units the question itself asks for, e.g. "nghỉ bao nhiêu giờ" -> ["hour"]."""
    return [name for name, words in UNITS.items()
            if any(re.search(rf"(?<!\w){re.escape(word)}(?!\w)", normalized) for word in words)]


def quantity_units(text: str) -> set[str]:
    """Units that actually carry a number in this text, e.g. "24 giờ liên tục" -> {"hour"}."""
    found = set()
    for name, words in UNITS.items():
        for word in words:
            if re.search(rf"\d+(?:[.,]\d+)?\s*{re.escape(word)}(?!\w)", text):
                found.add(name)
    return found


def analyze_query(text: str) -> dict:
    normalized = normalize(text)
    concepts = [name for name, phrases in CONCEPTS.items() if any(p in normalized for p in phrases)]
    legal_refs = re.findall(r"(?:điều|khoản)\s+\d+[a-z]?", normalized)
    numbers = re.findall(r"\d+(?:[.,]\d+)?(?:\s*%|\s*phần trăm|\s*triệu)?", normalized)
    return {"normalized": normalized, "concepts": concepts, "legal_refs": legal_refs,
            "numbers": numbers, "expected_units": expected_units(normalized)}


class Retriever:
    def __init__(self, documents: list[LegalDocument], provisions: list[Provision]):
        self.documents = {d.id: d for d in documents}
        self.provisions = provisions
        self.index_degraded = False
        self.doc_frequency = Counter()
        for p in provisions:
            self.doc_frequency.update(set(tokens(p.content)))

    def _eligible(self, p: Provision, on: date, domain: str | None, temporal: bool) -> bool:
        d = self.documents[p.document_id]
        if domain and d.domain != domain:
            return False
        return not temporal or (
            d.effective_from <= on and (d.effective_to is None or on <= d.effective_to)
        )

    def _scores(self, question: str, provision: Provision) -> tuple[float, float]:
        query, body = tokens(question), tokens(provision.content + " " + (provision.heading or ""))
        q, b = Counter(query), Counter(body)
        common = set(q) & set(b)
        cosine = sum(q[t] * b[t] for t in common) / (
            math.sqrt(sum(v * v for v in q.values())) * math.sqrt(sum(v * v for v in b.values()))
            or 1
        )
        n = len(self.provisions)
        bm25 = sum(
            (1 + math.log((n + 1) / (self.doc_frequency[t] + 1))) * b[t] / (b[t] + 1.2)
            for t in query
            if b[t]
        )
        return cosine, bm25

    def search(
        self, question: str, on: date, domain: str | None, level: str, top_k: int
    ) -> list[RetrievedProvision]:
        temporal = level in {"L2", "L3", "L4", "L7"}
        analysis = analyze_query(question)
        # Quantitative interrogatives and threshold words. "mấy" and "bao lâu" are as common
        # as "bao nhiêu" in spoken Vietnamese questions.
        numeric_answer_intent = bool(re.search(
            r"\b(bao nhiêu|bao lâu|mấy|mức|tỷ lệ|tối đa|tối thiểu|ít nhất|không quá)\b",
            analysis["normalized"]))
        production_scores: dict[str, tuple[float, float]] = {}
        self.index_degraded = False
        from apps.api.database import active_index_candidates, active_index_name
        from packages.generation.openai_gateway import OpenAIError, embed
        if active_index_name():
            try:
                vectors = embed([question])
            except OpenAIError:
                vectors = None
            if vectors:
                production_scores = active_index_candidates(
                    question, vectors[0], on, domain, temporal, max(top_k * 10, 50))
            # An embedding outage or a non-pgvector backend must not take retrieval down;
            # fall back to the deterministic lexical path and flag the degradation.
            self.index_degraded = not production_scores
        candidates = []
        for p in self.provisions:
            if not self._eligible(p, on, domain, temporal):
                continue
            if production_scores:
                if str(p.id) not in production_scores:
                    continue
                vector, keyword = production_scores[str(p.id)]
            else:
                vector, keyword = self._scores(question, p)
            candidates.append(
                RetrievedProvision(provision=p, vector_score=vector, keyword_score=keyword)
            )
        vector_rank = {
            x.provision.id: i + 1
            for i, x in enumerate(sorted(candidates, key=lambda x: x.vector_score, reverse=True))
        }
        keyword_rank = {
            x.provision.id: i + 1
            for i, x in enumerate(sorted(candidates, key=lambda x: x.keyword_score, reverse=True))
        }
        for item in candidates:
            if level in {"L1", "L2"}:
                item.fusion_score = item.vector_score
            else:
                item.fusion_score = 1 / (60 + vector_rank[item.provision.id]) + 1 / (
                    60 + keyword_rank[item.provision.id]
                )
            haystack = normalize(item.provision.content + " " + (item.provision.heading or ""))
            exact = len(set(tokens(question)) & set(tokens(haystack)))
            concept_hits = [
                concept for concept in analysis["concepts"]
                if any(phrase in haystack for phrase in CONCEPTS[concept])
            ]
            phrase_hit = analysis["normalized"] in haystack
            ref_hit = any(ref in haystack for ref in analysis["legal_refs"])
            # Reward a candidate that answers in the unit the question asked for. The old
            # check accepted any number in any unit, so "bao nhiêu giờ" was answered by
            # "200 phần trăm" — and that bonus alone outranked the correct provision.
            units_present = quantity_units(haystack)
            wanted = analysis["expected_units"]
            has_quantified_answer = bool(
                units_present & set(wanted) if wanted else units_present
            )
            legal_ref = (
                0.08
                if re.search(
                    r"\b(điều|khoản|phần trăm|triệu đồng)\b", normalize(item.provision.content)
                )
                else 0
            )
            item.rerank_score = (
                item.fusion_score * 15 + exact * 0.065 + len(concept_hits) * 0.13
                    + (0.16 if phrase_hit else 0) + (0.12 if ref_hit else 0) + legal_ref
                    + (0.18 if numeric_answer_intent and has_quantified_answer else 0)
                if level in {"L4", "L7"}
                else item.fusion_score
            )
            reasons = []
            if exact:
                reasons.append(f"Khớp {exact} từ khóa")
            if concept_hits:
                reasons.append("Đúng ý định: " + ", ".join(concept_hits))
            if phrase_hit:
                reasons.append("Khớp cụm từ chính xác")
            if temporal:
                reasons.append("Có hiệu lực tại ngày hỏi")
            if numeric_answer_intent and has_quantified_answer:
                reasons.append("Có giá trị định lượng cần trả lời")
            item.match_reasons = reasons
        key = (lambda x: x.rerank_score) if level in {"L4", "L7"} else (lambda x: x.fusion_score)
        return [
            x
            for x in sorted(candidates, key=key, reverse=True)
            if x.vector_score > 0 or x.keyword_score > 0
        ][:top_k]
