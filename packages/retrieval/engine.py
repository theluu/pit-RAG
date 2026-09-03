import math
import re
from collections import Counter
from datetime import date

from apps.api.models import LegalDocument, Provision, RetrievedProvision
from packages.ingestion.parser import normalize

STOP = {"là", "và", "có", "được", "theo", "cho", "của", "với", "một", "những", "gì", "bao", "nhiêu"}


def tokens(text: str) -> list[str]:
    return [x for x in re.findall(r"\w+", normalize(text)) if len(x) > 1 and x not in STOP]


class Retriever:
    def __init__(self, documents: list[LegalDocument], provisions: list[Provision]):
        self.documents = {d.id: d for d in documents}
        self.provisions = provisions
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
        candidates = []
        for p in self.provisions:
            if not self._eligible(p, on, domain, temporal):
                continue
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
            exact = len(set(tokens(question)) & set(tokens(item.provision.content)))
            legal_ref = (
                0.08
                if re.search(
                    r"\b(điều|khoản|phần trăm|triệu đồng)\b", normalize(item.provision.content)
                )
                else 0
            )
            item.rerank_score = (
                min(1, item.fusion_score * 15 + exact * 0.08 + legal_ref)
                if level in {"L4", "L7"}
                else item.fusion_score
            )
        key = (lambda x: x.rerank_score) if level in {"L4", "L7"} else (lambda x: x.fusion_score)
        return [
            x
            for x in sorted(candidates, key=key, reverse=True)
            if x.vector_score > 0 or x.keyword_score > 0
        ][:top_k]
