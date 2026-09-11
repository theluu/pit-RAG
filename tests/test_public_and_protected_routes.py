"""Search is public; everything that changes or exposes the system needs a login.

The deployed bundle shipped the demo account's email and password as literals, and that
account holds the admin role — so anyone who opened DevTools on rag.themeshub.net could
mint an admin token and upload, publish, edit metadata, rebuild the index or read the
audit log. Hiding the admin tabs in the UI protected nothing; the API was the boundary
and it was open.

The split drawn here:

  public      reading the corpus and asking a question — no account, no barrier
  login       anything that writes, anything that costs several LLM calls per request,
              and anything that reports provider configuration or internal errors
"""

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app

PUBLIC_READS = [
    ("get", "/api/v1/documents"),
    ("get", "/api/v1/relations"),
]

PROTECTED = [
    ("get", "/api/v1/capabilities"),
    ("get", "/api/v1/admin/summary"),
    ("get", "/api/v1/admin/documents"),
    ("get", "/api/v1/admin/indexes"),
    ("get", "/api/v1/admin/audit"),
    ("post", "/api/v1/admin/indexes/rebuild"),
    ("post", "/api/v1/admin/evaluations/L4"),
    ("post", "/api/v1/query/compare"),
]


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth(client):
    r = client.post("/api/v1/auth/login",
                    json={"email": "demo@legalrag.vn", "password": "demo1234"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def call(client, method, path, **kw):
    return getattr(client, method)(path, **kw)


# ---------------------------------------------------------------- public


def test_a_visitor_with_no_account_can_search(client):
    r = client.post("/api/v1/query", json={"question": "Thời gian thử việc tối đa là bao lâu?"})

    assert r.status_code == 200, r.text
    assert "answer" in r.json()


@pytest.mark.parametrize("method,path", PUBLIC_READS)
def test_reading_the_corpus_needs_no_account(client, method, path):
    assert call(client, method, path).status_code == 200


def test_a_visitor_can_reopen_a_result_by_its_run_id(client):
    run_id = client.post("/api/v1/query", json={"question": "Thời gian thử việc tối đa?"}).json()["run_id"]

    assert client.get(f"/api/v1/runs/{run_id}").status_code == 200


def test_a_visitor_can_leave_feedback(client):
    run_id = client.post("/api/v1/query", json={"question": "Thời gian thử việc tối đa?"}).json()["run_id"]

    r = client.post(f"/api/v1/runs/{run_id}/feedback", json={"rating": "correct"})
    assert r.status_code == 201


def test_an_anonymous_search_is_still_attributed_to_someone(client):
    """A run row with no owner would break the admin listing and the audit trail."""
    from apps.api.database import get_run

    run_id = client.post("/api/v1/query", json={"question": "Giảm trừ gia cảnh?"}).json()["run_id"]
    assert get_run(run_id) is not None


def test_a_bad_token_does_not_break_a_public_search(client):
    """A stale token in localStorage must degrade to anonymous, not to a 401."""
    r = client.post("/api/v1/query", json={"question": "Thời gian thử việc tối đa?"},
                    headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 200


# ---------------------------------------------------------------- protected


@pytest.mark.parametrize("method,path", PROTECTED)
def test_without_a_token_it_is_refused(client, method, path):
    body = {"question": "x?", "pipelines": ["L1"]} if "compare" in path else None
    r = call(client, method, path, **({"json": body} if body else {}))
    assert r.status_code == 401, f"{path} answered {r.status_code}"


@pytest.mark.parametrize("method,path", PROTECTED)
def test_a_forged_token_is_refused(client, method, path):
    body = {"question": "x?", "pipelines": ["L1"]} if "compare" in path else None
    kw = {"headers": {"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.forged.sig"}}
    if body:
        kw["json"] = body
    r = call(client, method, path, **kw)
    assert r.status_code == 401, f"{path} answered {r.status_code}"


@pytest.mark.parametrize("method,path", PROTECTED)
def test_a_real_login_gets_through(client, auth, method, path):
    body = {"question": "Thời gian thử việc?", "pipelines": ["L1"]} if "compare" in path else None
    kw = {"headers": auth}
    if body:
        kw["json"] = body
    r = call(client, method, path, **kw)
    assert r.status_code < 400, f"{path} answered {r.status_code}: {r.text[:200]}"


def test_writing_a_document_without_a_login_is_refused(client):
    r = client.post("/api/v1/admin/documents", json={
        "document_number": "HACK/2026", "title": "Văn bản giả mạo",
        "document_type": "Luật", "issuing_authority": "X", "issued_date": "2026-01-01",
        "effective_from": "2026-01-01", "domain": "labor",
        "text": "Điều 1. Phạm vi\n1. Nội dung.\n", "publish": True,
    })
    assert r.status_code == 401


def test_the_provider_configuration_is_not_public(client):
    """capabilities reports the model in use and the last provider error."""
    assert client.get("/api/v1/capabilities").status_code == 401
