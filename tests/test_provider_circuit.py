"""Circuit-breaker behaviour for the OpenAI gateway.

One slow chat call used to open a single shared breaker for 60 seconds. That disabled
embeddings too, which silently dropped retrieval onto the lexical path — so a transient
timeout on the *generation* endpoint changed which provisions were *retrieved*.
"""

import pytest
from openai import APITimeoutError

from apps.api.config import settings
from packages.generation import openai_gateway as gw


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(settings, "enable_openai", True)
    monkeypatch.setattr(settings, "openai_failure_threshold", 3)
    monkeypatch.setattr(gw, "_client", lambda: object())
    gw.reset_circuits()
    yield
    gw.reset_circuits()


def timeout() -> APITimeoutError:
    return APITimeoutError(request=None)


def test_a_single_failure_does_not_trip_the_breaker():
    gw._failure("chat", timeout())
    assert gw._available("chat")
    assert gw.provider_status()["chat"]["failures"] == 1


def test_breaker_opens_only_at_the_threshold():
    for _ in range(settings.openai_failure_threshold - 1):
        gw._failure("chat", timeout())
    assert gw._available("chat")
    gw._failure("chat", timeout())
    assert not gw._available("chat")
    assert gw.provider_status()["chat"]["circuit_open"]


def test_a_success_clears_the_failure_run():
    gw._failure("chat", timeout())
    gw._failure("chat", timeout())
    gw._success("chat")
    gw._failure("chat", timeout())
    assert gw._available("chat"), "failures must be consecutive to count"


def test_chat_outage_leaves_embeddings_and_therefore_retrieval_alone():
    for _ in range(settings.openai_failure_threshold):
        gw._failure("chat", timeout())
    assert not gw._available("chat")
    assert gw._available("embeddings"), "a chat outage must not degrade the vector index path"

    status = gw.provider_status()
    assert status["chat"]["circuit_open"] and not status["embeddings"]["circuit_open"]
    assert status["circuit_open"], "the summary flag still reports a degraded provider"


def test_embedding_outage_is_reported_independently():
    for _ in range(settings.openai_failure_threshold):
        gw._failure("embeddings", timeout())
    assert not gw._available("embeddings")
    assert gw._available("chat")
    assert gw.provider_status()["embeddings"]["last_error"] == "APITimeoutError"


def test_embed_returns_none_instead_of_raising_when_its_breaker_is_open():
    for _ in range(settings.openai_failure_threshold):
        gw._failure("embeddings", timeout())
    assert gw.embed(["bất kỳ"]) is None
