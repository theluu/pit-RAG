from uuid import uuid4

from fastapi.testclient import TestClient

from apps.api.config import settings
from apps.api.main import app

client = TestClient(app)


def token():
    response = client.post(
        "/api/v1/auth/login", json={"email": settings.demo_username, "password": settings.demo_password}
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
    assert response.json()["legal_timeline"]
    assert response.json()["generation_mode"] in {"openai", "extractive_fallback"}


def test_l0_never_fabricates_citation():
    response = client.post(
        "/api/v1/query",
        headers={"Authorization": f"Bearer {token()}"},
        json={"question": "Một câu hỏi pháp lý", "pipeline_level": "L0"},
    )
    assert response.json()["citations"] == []


def test_query_exposes_auditable_legal_signals():
    response = client.post(
        "/api/v1/query",
        headers={"Authorization": f"Bearer {token()}"},
        json={
            "question": "Tăng ca cuối tuần được trả thế nào?",
            "domain": "labor",
            "applicable_date": "2026-01-01",
            "pipeline_level": "L7",
        },
    )
    body = response.json()
    assert {"overtime", "weekly_rest"} <= set(body["query_analysis"]["concepts"])
    assert body["diagnostics"]["effective_date_checked"] is True
    assert body["diagnostics"]["evidence_count"] > 0
    assert body["diagnostics"]["graph_path"] in {"neo4j", "sql_fallback"}
    assert any(x["match_reasons"] for x in body["retrieved_provisions"])


def test_curator_ingest_stays_draft_until_published():
    document_number = f"TEST/{uuid4()}"
    response = client.post(
        "/api/v1/admin/documents",
        headers={"Authorization": f"Bearer {token()}"},
        json={
            "document_number": document_number,
            "title": "Văn bản kiểm thử ingestion",
            "document_type": "Nghị quyết",
            "issuing_authority": "Cơ quan kiểm thử",
            "issued_date": "2026-01-01",
            "effective_from": "2026-02-01",
            "domain": "labor",
            "text": "Điều 1. Quy định kiểm thử\n1. Nội dung chỉ dùng để kiểm thử ingestion.",
            "publish": False,
        },
    )
    assert response.status_code == 201
    assert response.json()["published"] is False
    assert response.json()["document"]["status"] == "draft"
    document_id = response.json()["document"]["id"]
    published = client.post(
        f"/api/v1/admin/documents/{document_id}/publish",
        headers={"Authorization": f"Bearer {token()}"},
    )
    assert published.status_code == 200
    assert published.json()["index_documents"] >= 6


def test_evaluation_endpoint_reports_citation_quality():
    response = client.post(
        "/api/v1/admin/evaluations/L7",
        headers={"Authorization": f"Bearer {token()}"},
    )
    assert response.status_code == 200
    assert response.json()["cases"] == 3
    assert response.json()["citation_recall"] == 1
    assert response.json()["citation_precision"] == 1


def test_operational_readiness_and_admin_summary():
    readiness = client.get("/ready")
    assert readiness.status_code == 200
    assert readiness.json()["database"] is True
    summary = client.get(
        "/api/v1/admin/summary",
        headers={"Authorization": f"Bearer {token()}"},
    )
    assert summary.status_code == 200
    assert summary.json()["published_index_documents"] >= 5
    assert "provider" in summary.json()["capabilities"]
    graph = summary.json()["capabilities"]["neo4j"]
    assert {"enabled", "available", "nodes", "relationships"} <= set(graph)
