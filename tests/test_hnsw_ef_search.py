"""hnsw.ef_search must stay inside the range pgvector accepts.

Reproduces a 500 on the dev deployment: every L5/L6/L7 query failed with

    psycopg.errors.InvalidParameterValue: 3600 is outside the valid range
    for parameter "hnsw.ef_search" (1 .. 1000)

The graph and multi-query levels ask for ~450 candidates, and `ann_overfetch` (8)
multiplies that into 3600. PostgreSQL rejects the whole statement rather than clamping,
so the levels that most need recall were the only ones that could not run at all.

The bug stayed hidden until a production index was activated — without one,
`active_index_candidates` returns early and never issues the SET LOCAL.
"""

import pytest

from apps.api.config import settings
from apps.api.database import HNSW_EF_SEARCH_MAX, _ef_search


def test_the_overfetch_that_broke_l5_to_l7_is_clamped():
    assert _ef_search(3600) == HNSW_EF_SEARCH_MAX


def test_clamp_matches_the_limit_pgvector_documents():
    assert HNSW_EF_SEARCH_MAX == 1000


@pytest.mark.parametrize("overfetch", [1, 40, 120, 400, 999, 1000])
def test_values_within_range_are_left_alone(overfetch):
    expected = max(settings.hnsw_ef_search, overfetch)
    assert _ef_search(overfetch) == expected


def test_configured_floor_still_wins_over_a_small_overfetch():
    assert _ef_search(1) == settings.hnsw_ef_search


def test_result_is_always_a_legal_pgvector_value():
    for overfetch in (0, 1, 500, 5000, 10**6):
        assert 1 <= _ef_search(overfetch) <= HNSW_EF_SEARCH_MAX
