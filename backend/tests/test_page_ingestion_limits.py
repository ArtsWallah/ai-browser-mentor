"""
Backend Regression Tests for Page Ingestion Limits & Compatibility

Verifies:
1. Valid page ingestion payload (< 2 MB) succeeds with HTTP 200.
2. Ingested page is accessible in the page store via get_page().
3. Summarization and explanation commands function properly with ingested page context.
4. Downstream /command/execute behaves safely and cleanly when page context is not found.
5. Payloads exceeding 2 MB are rejected with HTTP 413 by RequestSizeLimitMiddleware.
"""

import pytest
from starlette.testclient import TestClient
from app.main import app, MAX_REQUEST_BODY_SIZE, get_page


@pytest.fixture
def client():
    return TestClient(app)


def test_valid_page_ingestion_succeeds(client):
    """Confirm a standard-sized, structured page payload succeeds with 200."""
    payload = {
        "page_id": "test_page_normal_1",
        "title": "Introduction to Browser Security",
        "url": "https://example.com/security",
        "hostname": "example.com",
        "description": "An overview of web application security principles.",
        "headings": ["Overview", "Authentication Best Practices"],
        "paragraphs": [],
        "chunks": [
            {
                "heading": "Overview",
                "text": "Web security involves protecting web applications against unauthorized access, use, or data compromise.",
                "level": 1,
                "type": "section"
            },
            {
                "heading": "Authentication Best Practices",
                "text": "Authentication ensures that users are who they claim to be using strong passwords and multi-factor authentication.",
                "level": 2,
                "type": "section"
            }
        ],
        "links": [
            {"index": 0, "text": "Home", "url": "https://example.com"},
            {"index": 1, "text": "Login", "url": "https://example.com/login"}
        ],
        "images": [
            {"index": 0, "src": "https://example.com/logo.png", "alt": "Logo", "title": "Logo"}
        ],
        "interactiveElements": [
            {"index": 0, "tag": "input", "type": "password", "role": "", "text": "Password", "ariaLabel": "Password", "placeholder": "Password", "href": ""}
        ],
        "content": "Web security involves protecting web applications. Authentication ensures that users are who they claim to be.",
        "wordCount": 35
    }

    res = client.post("/page/ingest", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data.get("page_id") == "test_page_normal_1"
    assert data.get("page_state") in ("ready", "low_content")
    assert data.get("chunkCount") == 2


def test_get_ingested_page_roundtrip(client):
    """Confirm an ingested page is properly saved and retrievable via get_page()."""
    page = get_page("test_page_normal_1")
    assert page is not None
    assert page.get("page_id") == "test_page_normal_1"
    assert page.get("title") == "Introduction to Browser Security"


def test_command_execution_with_ingested_page(client):
    """Confirm AI Command Center can summarize the ingested page."""
    cmd_payload = {
        "instruction": "Summarize this page",
        "intent": "summarize_page",
        "page_id": "test_page_normal_1",
        "selection_text": "",
        "page_url": "https://example.com/security",
        "page_title": "Introduction to Browser Security",
        "privacy_mode": "hybrid"
    }

    res = client.post("/command/execute", json=cmd_payload)
    assert res.status_code == 200
    data = res.json()
    assert data.get("success") is True
    assert data.get("intent") == "summarize_page"
    assert len(data.get("key_points", [])) > 0 or len(data.get("answer", "")) > 0


def test_command_execution_with_missing_page_fails_gracefully(client):
    """Confirm AI Command Center handles nonexistent page_id gracefully without crash."""
    cmd_payload = {
        "instruction": "Summarize this page",
        "intent": "summarize_page",
        "page_id": "nonexistent_page_9999",
        "selection_text": "",
        "page_url": "https://example.com/missing",
        "page_title": "Missing Page",
        "privacy_mode": "hybrid"
    }

    res = client.post("/command/execute", json=cmd_payload)
    assert res.status_code == 200
    data = res.json()
    assert data.get("success") is False
    assert "No page chunks" in (data.get("error") or "") or "not loaded" in (data.get("answer") or "").lower() or "not indexed" in (data.get("action_summary") or "").lower()


def test_oversized_payload_rejected_with_413(client):
    """Confirm payloads exceeding MAX_REQUEST_BODY_SIZE are rejected with HTTP 413."""
    oversized_data = "X" * (MAX_REQUEST_BODY_SIZE + 1024)
    huge_payload = {
        "page_id": "huge_page_fail",
        "title": "Oversized Page",
        "content": oversized_data
    }

    res = client.post("/page/ingest", json=huge_payload)
    assert res.status_code == 413
    data = res.json()
    assert data.get("success") is False
    assert "Request entity too large" in data.get("error", "")
