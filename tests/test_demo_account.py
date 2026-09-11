"""The demo account is seeded from configuration, not frozen in code.

Two things have to stay true at once: a visitor needs no account to search, and the
demo account has to be usable by whoever is being shown the system. The credentials
therefore come from settings so a deployment can change them without a code change —
the previous pair was a literal in the source, which is how it ended up in the browser
bundle.

Seeding is an upsert on purpose: a demo account whose password drifts away from the
configured one is a demo nobody can sign into.
"""

import pytest
from fastapi.testclient import TestClient

from apps.api.config import settings
from apps.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def login(client, username, password):
    return client.post("/api/v1/auth/login", json={"email": username, "password": password})


def test_the_configured_demo_account_can_sign_in(client):
    r = login(client, settings.demo_username, settings.demo_password)

    assert r.status_code == 200, r.text
    assert r.json()["access_token"]


def test_the_demo_account_defaults_to_demo_demo():
    assert (settings.demo_username, settings.demo_password) == ("demo", "demo")


def test_a_username_does_not_have_to_look_like_an_email(client):
    """The login field is named `email` for API compatibility; "demo" must still work."""
    assert login(client, "demo", "demo").status_code == 200


def test_the_wrong_password_is_refused(client):
    assert login(client, settings.demo_username, "khong-dung").status_code == 401


def test_an_unknown_account_is_refused(client):
    assert login(client, "khong-ton-tai", "demo").status_code == 401


def test_the_demo_account_still_reaches_the_admin_area(client):
    token = login(client, settings.demo_username, settings.demo_password).json()["access_token"]

    r = client.get("/api/v1/admin/summary", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_searching_still_needs_no_account_at_all(client):
    """The point of the demo account is convenience, not a gate in front of search."""
    r = client.post("/api/v1/query", json={"question": "Thời gian thử việc tối đa là bao lâu?"})
    assert r.status_code == 200
