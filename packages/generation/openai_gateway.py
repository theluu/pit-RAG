import json
import time
from functools import lru_cache

from openai import OpenAI, OpenAIError

from apps.api.config import settings
from apps.api.models import Citation, RetrievedProvision

SYSTEM_PROMPT = """Bạn là trợ lý tra cứu pháp luật Việt Nam. Chỉ sử dụng evidence được cung cấp.
Không tự tạo số hiệu, điều, khoản, con số hoặc ngoại lệ. Mỗi claim phải liệt kê provision_id hỗ trợ.
Nếu evidence không đủ, đặt abstained=true. Trả lời ngắn gọn bằng tiếng Việt."""
# Chat and embeddings are separate endpoints with separate failure modes, and they are
# consumed by different parts of the system: chat writes the answer, embeddings decide
# whether retrieval can use the production vector index at all. A shared breaker meant one
# slow chat call silently downgraded retrieval to the lexical path for a full minute, which
# is how a timeout turned into a wrong legal answer.
_CIRCUITS = {
    "chat": {"failures": 0, "open_until": 0.0, "last_error": None},
    "embeddings": {"failures": 0, "open_until": 0.0, "last_error": None},
}


@lru_cache(maxsize=1)
def _client():
    if not settings.openai_api_key:
        return None
    return OpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.openai_timeout_seconds,
        max_retries=0,
    )


def reset_circuits() -> None:
    for circuit in _CIRCUITS.values():
        circuit.update(failures=0, open_until=0.0, last_error=None)


def _configured() -> bool:
    return settings.enable_openai and _client() is not None


def _is_open(endpoint: str) -> bool:
    return time.monotonic() < _CIRCUITS[endpoint]["open_until"]


def _available(endpoint: str) -> bool:
    return _configured() and not _is_open(endpoint)


def _success(endpoint: str) -> None:
    _CIRCUITS[endpoint].update(failures=0, open_until=0.0, last_error=None)


def _failure(endpoint: str, exc: Exception) -> None:
    """Trip the breaker only after repeated failures.

    A single timeout is a blip, not an outage; opening on the first one costs a minute of
    degraded service for what is often one slow request.
    """
    circuit = _CIRCUITS[endpoint]
    circuit["failures"] += 1
    circuit["last_error"] = type(exc).__name__
    if circuit["failures"] >= settings.openai_failure_threshold:
        circuit["open_until"] = time.monotonic() + settings.openai_circuit_seconds


def provider_status() -> dict:
    configured = _configured()
    chat_open, embed_open = _is_open("chat"), _is_open("embeddings")
    return {
        "configured": configured,
        # Kept for existing callers: "fully healthy".
        "available": configured and not chat_open and not embed_open,
        "circuit_open": configured and (chat_open or embed_open),
        "last_error": _CIRCUITS["chat"]["last_error"] or _CIRCUITS["embeddings"]["last_error"],
        "model": settings.openai_chat_model,
        "embedding_model": settings.openai_embedding_model,
        "chat": {"available": configured and not chat_open, "circuit_open": chat_open,
                 "failures": _CIRCUITS["chat"]["failures"],
                 "last_error": _CIRCUITS["chat"]["last_error"]},
        "embeddings": {"available": configured and not embed_open, "circuit_open": embed_open,
                       "failures": _CIRCUITS["embeddings"]["failures"],
                       "last_error": _CIRCUITS["embeddings"]["last_error"]},
    }


def embed(texts: list[str]) -> list[list[float]] | None:
    client = _client()
    if not _available("embeddings") or client is None:
        return None
    try:
        response = client.embeddings.create(model=settings.openai_embedding_model, input=texts)
    except OpenAIError as exc:
        _failure("embeddings", exc)
        raise
    _success("embeddings")
    return [item.embedding for item in response.data]


def grounded_answer(question: str, results: list[RetrievedProvision]) -> dict | None:
    client = _client()
    if not _available("chat") or client is None or not results:
        return None
    evidence = [
        {
            "provision_id": str(item.provision.id),
            "location": f"Điều {item.provision.article}, khoản {item.provision.clause or '-'}, "
            f"điểm {item.provision.point or '-'}",
            "content": item.provision.content,
        }
        for item in results[:5]
    ]
    try:
        response = client.responses.create(
            model=settings.openai_chat_model,
            instructions=SYSTEM_PROMPT,
            input=json.dumps({"question": question, "evidence": evidence}, ensure_ascii=False),
            text={"format": {"type": "json_schema", "name": "grounded_legal_answer",
                "strict": True, "schema": {"type": "object", "properties": {
                    "answer": {"type": "string"}, "claim_provision_ids": {
                        "type": "array", "items": {"type": "string"}},
                    "abstained": {"type": "boolean"}},
                    "required": ["answer", "claim_provision_ids", "abstained"],
                    "additionalProperties": False}}},
        )
    except OpenAIError as exc:
        _failure("chat", exc)
        raise
    _success("chat")
    parsed = json.loads(response.output_text)
    allowed = {str(item.provision.id) for item in results}
    cited = set(parsed["claim_provision_ids"])
    if not cited <= allowed or (not parsed["abstained"] and not cited):
        return None
    return parsed


def verify_citations(citations: list[Citation], results: list[RetrievedProvision]) -> bool:
    source = {item.provision.id: item.provision.content for item in results}
    return all(c.provision_id in source and c.quote in source[c.provision_id] for c in citations)
