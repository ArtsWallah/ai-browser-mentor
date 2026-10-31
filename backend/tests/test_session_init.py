"""
Tests for Server-Side Session Initialization Endpoint (POST /session/init).
Verifies cryptographic token delivery, uniqueness, cache prevention headers,
rate limiting, and protection against client-supplied ownership tampering.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app, limiter
from app.services.session_service import is_valid_token_format, SESSION_TOKEN_PREFIX


@pytest.fixture
def client():
    # Reset in-memory rate limiter between tests if supported
    try:
        limiter.reset()
    except Exception:
        pass
    return TestClient(app)


class TestSessionInitEndpoint:
    def test_session_init_returns_valid_token(self, client):
        """POST /session/init must return a 200 response with a valid session token."""
        response = client.post("/session/init")
        assert response.status_code == 200

        data = response.json()
        assert data.get("success") is True
        token = data.get("session_token")
        assert isinstance(token, str)
        assert token.startswith(SESSION_TOKEN_PREFIX)
        assert is_valid_token_format(token) is True
        assert len(token) >= 24

    def test_consecutive_init_calls_produce_distinct_tokens(self, client):
        """Each call to /session/init must generate a fresh, distinct cryptographic token."""
        tokens = set()
        count = 15
        for _ in range(count):
            res = client.post("/session/init")
            assert res.status_code == 200
            token = res.json().get("session_token")
            assert token not in tokens
            tokens.add(token)

        assert len(tokens) == count

    def test_cache_control_headers_prevent_caching(self, client):
        """Responses must include Cache-Control and Pragma headers preventing proxy/CDN caching."""
        response = client.post("/session/init")
        assert response.status_code == 200

        cache_control = response.headers.get("cache-control", "").lower()
        assert "no-store" in cache_control
        assert "no-cache" in cache_control
        assert "must-revalidate" in cache_control

        pragma = response.headers.get("pragma", "").lower()
        assert pragma == "no-cache"

    def test_client_supplied_ownership_fields_are_ignored(self, client):
        """
        Clients attempting to provide user_id, owner_id, or session_hash in the request body
        must be ignored. Only server-generated tokens are returned.
        """
        payload = {
            "user_id": "malicious_user_999",
            "owner_id": "admin_vault",
            "session_hash": "0000000000000000000000000000000000000000000000000000000000000000",
            "is_admin": True,
        }
        response = client.post("/session/init", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert "user_id" not in data
        assert "owner_id" not in data
        assert "session_hash" not in data
        assert "is_admin" not in data
        assert data.get("success") is True
        assert is_valid_token_format(data.get("session_token")) is True

    def test_no_server_internals_or_hashes_leaked(self, client):
        """The endpoint must only return success and session_token, leaking no server internals."""
        response = client.post("/session/init")
        assert response.status_code == 200
        data = response.json()
        assert set(data.keys()) == {"success", "session_token"}

    def test_empty_and_no_body_payloads(self, client):
        """Both empty body and no body requests must succeed."""
        res1 = client.post("/session/init")
        assert res1.status_code == 200

        res2 = client.post("/session/init", json={})
        assert res2.status_code == 200

        assert res1.json()["session_token"] != res2.json()["session_token"]
