"""A document's metadata has to be correctable after ingestion.

The admin upload form stamps document_type, issuing_authority, issued_date,
effective_from and domain on a PDF the uploader never gets to describe. Retrieval
filters on exactly those fields, so a wrong effective_from hides the document from
every search made for an earlier date — which is how Luật An toàn, vệ sinh lao động
came to answer "Chưa đủ căn cứ" while sitting published in the corpus.

Until now the only route to a fix was re-ingesting the file, which discards a 59-page
OCR extraction to correct a date, or an UPDATE straight against the database.
"""

from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def token(client):
    r = client.post("/api/v1/auth/login",
                    json={"email": "demo@legalrag.vn", "password": "demo1234"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture
def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def document(client, auth):
    """A published document whose metadata is deliberately wrong."""
    body = {
        "document_number": f"TEST-META/{uuid4().hex[:8]}",
        "title": "Văn bản dùng để kiểm thử sửa metadata",
        "document_type": "Nghị quyết",
        "issuing_authority": "Cơ quan demo",
        "issued_date": "2026-01-01",
        "effective_from": "2026-02-01",
        "domain": "labor",
        "text": ("Điều 1. Phạm vi điều chỉnh\n"
                 "1. Văn bản này quy định về thời giờ làm việc của người lao động.\n"),
        "publish": True,
    }
    r = client.post("/api/v1/admin/documents", json=body, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()["document"]


def patch(client, auth, doc_id, **changes):
    return client.patch(f"/api/v1/admin/documents/{doc_id}", json=changes, headers=auth)


def test_correcting_the_effective_date_keeps_the_provisions(client, auth, document):
    before = client.get(f"/api/v1/documents/{document['id']}", headers=auth).json()
    r = patch(client, auth, document["id"], effective_from="2016-07-01")

    assert r.status_code == 200, r.text
    assert r.json()["document"]["effective_from"] == "2016-07-01"
    after = client.get(f"/api/v1/documents/{document['id']}", headers=auth).json()
    assert len(after["provisions"]) == len(before["provisions"])


def test_several_fields_at_once(client, auth, document):
    r = patch(client, auth, document["id"],
              document_type="Luật", issuing_authority="Quốc hội",
              issued_date="2015-06-25", effective_from="2016-07-01")

    assert r.status_code == 200, r.text
    doc = r.json()["document"]
    assert (doc["document_type"], doc["issuing_authority"]) == ("Luật", "Quốc hội")
    assert doc["issued_date"] == "2015-06-25"
    assert sorted(r.json()["fields"]) == [
        "document_type", "effective_from", "issued_date", "issuing_authority",
    ]


def test_untouched_fields_are_preserved(client, auth, document):
    r = patch(client, auth, document["id"], document_type="Luật")

    assert r.json()["document"]["title"] == document["title"]
    assert r.json()["document"]["domain"] == document["domain"]


def test_renaming_the_document_number_is_reflected_in_the_admin_listing(client, auth, document):
    renamed = f"84-2015-QH13/{uuid4().hex[:8]}"
    r = patch(client, auth, document["id"], document_number=renamed)
    assert r.status_code == 200, r.text

    listed = client.get("/api/v1/admin/documents", headers=auth).json()
    numbers = {d["document_number"] for d in listed}
    assert renamed in numbers and document["document_number"] not in numbers


def test_a_duplicate_document_number_is_refused(client, auth, document):
    r = patch(client, auth, document["id"], document_number="45/2019/QH14")
    assert r.status_code == 409


def test_an_empty_body_is_refused_rather_than_silently_doing_nothing(client, auth, document):
    assert patch(client, auth, document["id"]).status_code == 422


def test_an_unknown_document_is_404(client, auth):
    r = patch(client, auth, "00000000-0000-0000-0000-000000000000", document_type="Luật")
    assert r.status_code == 404


def test_the_caller_is_told_the_index_must_be_rebuilt(client, auth, document):
    """document_number rides in the index search_text, so the answer is always yes."""
    r = patch(client, auth, document["id"], title="Tiêu đề đã sửa")
    assert r.json()["reindex_required"] is True


def test_the_correction_is_audited(client, auth, document):
    patch(client, auth, document["id"], effective_from="2016-07-01")

    events = client.get("/api/v1/admin/audit", headers=auth).json()
    assert any(e["action"] == "document.metadata" for e in events)


def test_an_anonymous_caller_cannot_edit(client, document):
    r = client.patch(f"/api/v1/admin/documents/{document['id']}",
                     json={"document_type": "Luật"})
    assert r.status_code in (401, 403)


def test_a_corrected_effective_date_changes_what_a_dated_search_sees(client, auth, document):
    """The whole point: retrieval filters on this field."""
    patch(client, auth, document["id"], effective_from="2016-07-01")
    doc = client.get(f"/api/v1/documents/{document['id']}", headers=auth).json()["document"]
    assert date.fromisoformat(doc["effective_from"]) < date(2026, 1, 1)
