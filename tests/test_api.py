from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


def token():
    response = client.post(
        "/api/v1/auth/login", json={"email": "demo@legalrag.vn", "password": "demo1234"}
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_grounded_query_has_verified_citation():
    response = client.post(
        "/api/v1/query",
        headers={"Authorization": f"Bearer {token()}"},
        json={
            "question": "Làm thêm ngày nghỉ hằng tuần được trả bao nhiêu phần trăm?",
            "domain": "labor",
            "applicable_date": "2026-01-01",
            "pipeline_level": "L4",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["citations"]
    assert any("45/2019/QH14" == x["document_number"] for x in body["citations"])


def test_temporal_filter_uses_new_social_insurance_law():
    response = client.post(
        "/api/v1/query",
        headers={"Authorization": f"Bearer {token()}"},
        json={
            "question": "Đóng bảo hiểm bao nhiêu năm để hưởng lương hưu?",
            "domain": "social_insurance",
            "applicable_date": "2026-01-01",
            "pipeline_level": "L7",
        },
    )
    numbers = [x["document_number"] for x in response.json()["citations"]]
    assert "41/2024/QH15" in numbers
    assert "58/2014/QH13" not in numbers


def test_l0_never_fabricates_citation():
    response = client.post(
        "/api/v1/query",
        headers={"Authorization": f"Bearer {token()}"},
        json={"question": "Một câu hỏi pháp lý", "pipeline_level": "L0"},
    )
    assert response.json()["citations"] == []
