"""Shared test setup.

The API rate-limits 60 requests per minute per client address. Under TestClient every
test shares one address, so a full suite run trips the limiter and tests start failing
with 429 for reasons that have nothing to do with what they assert — and the failure
moves around as tests are added, which makes it look like flakiness.

The limiter is a production guard, not a property each test should have to fight, so it
is lifted by default here. A test that wants to exercise the limiter itself can put the
setting back with monkeypatch.
"""

import pytest

from apps.api.config import settings


@pytest.fixture(autouse=True)
def unlimited_requests(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 1_000_000)
