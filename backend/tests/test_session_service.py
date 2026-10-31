import math
import re
import pytest
from fastapi import FastAPI, Depends, status
from fastapi.testclient import TestClient
from fastapi.exceptions import HTTPException

from app.services.session_service import (
    create_session_token,
    hash_session_token,
    extract_session_token,
    get_current_session_hash,
    require_session_hash,
    is_valid_token_format,
    SESSION_TOKEN_PREFIX,
    MIN_TOKEN_LENGTH,
)


class TestSessionTokenGeneration:
    def test_tokens_are_distinct(self):
        """Verify 1,000 generated tokens are all distinct with zero collisions."""
        count = 1000
        tokens = [create_session_token() for _ in range(count)]
        assert len(set(tokens)) == count

    def test_token_format_and_prefix(self):
        token = create_session_token()
        assert token.startswith(SESSION_TOKEN_PREFIX)
        assert len(token) >= MIN_TOKEN_LENGTH
        assert is_valid_token_format(token) is True

    def test_token_without_prefix(self):
        token = create_session_token(prefix="")
        assert not token.startswith(SESSION_TOKEN_PREFIX)
        assert len(token) >= MIN_TOKEN_LENGTH
        assert is_valid_token_format(token) is True

    def test_token_entropy(self):
        """
        Verify the Shannon entropy of generated tokens.
        A base64url string with 32 bytes of randomness (~43 chars)
        has high information density (> 4.5 bits per character).
        """
        token = create_session_token(prefix="")
        char_counts = {}
        for c in token:
            char_counts[c] = char_counts.get(c, 0) + 1

        entropy = 0.0
        for count in char_counts.values():
            p = count / len(token)
            entropy -= p * math.log2(p)

        # High entropy threshold for random base64url data
        assert entropy > 4.2


class TestSessionTokenHashing:
    def test_hash_is_deterministic(self):
        token = create_session_token()
        hash1 = hash_session_token(token)
        hash2 = hash_session_token(token)
        assert hash1 == hash2

    def test_hash_format(self):
        token = create_session_token()
        digest = hash_session_token(token)
        # Must be exactly 64 characters long lowercase hex
        assert len(digest) == 64
        assert bool(re.match(r"^[0-9a-f]{64}$", digest))

    def test_different_tokens_produce_different_hashes(self):
        token1 = create_session_token()
        token2 = create_session_token()
        assert hash_session_token(token1) != hash_session_token(token2)

    def test_hash_rejects_empty_and_invalid_types(self):
        with pytest.raises(ValueError, match="must be a string"):
            hash_session_token(None)  # type: ignore

        with pytest.raises(ValueError, match="empty"):
            hash_session_token("")

        with pytest.raises(ValueError, match="empty"):
            hash_session_token("   ")

    def test_hash_rejects_malformed_token_format(self):
        with pytest.raises(ValueError, match="format is invalid"):
            hash_session_token("too_short")

        with pytest.raises(ValueError, match="format is invalid"):
            hash_session_token("token with spaces that is otherwise long enough")


class TestHeaderExtractionAndPrecedence:
    def test_extract_from_x_session_id(self):
        token = create_session_token()
        extracted = extract_session_token(x_session_id=token)
        assert extracted == token

    def test_extract_from_authorization_bearer(self):
        token = create_session_token()
        extracted = extract_session_token(authorization=f"Bearer {token}")
        assert extracted == token

    def test_extract_from_authorization_bearer_case_insensitive(self):
        token = create_session_token()
        extracted = extract_session_token(authorization=f"bearer {token}")
        assert extracted == token

    def test_precedence_rule_x_session_id_over_authorization(self):
        """
        PRECEDENCE RULE:
        X-Session-ID takes precedence over Authorization header when both are present.
        """
        token_primary = create_session_token(prefix="abm_s_primary_")
        token_secondary = create_session_token(prefix="abm_s_secondary_")

        extracted = extract_session_token(
            x_session_id=token_primary,
            authorization=f"Bearer {token_secondary}",
        )
        assert extracted == token_primary
        assert extracted != token_secondary

    def test_fallback_to_authorization_when_x_session_id_is_empty(self):
        token = create_session_token()
        extracted = extract_session_token(
            x_session_id="",
            authorization=f"Bearer {token}",
        )
        assert extracted == token

    def test_missing_token_raises_401(self):
        with pytest.raises(HTTPException) as exc_info:
            extract_session_token(x_session_id=None, authorization=None)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Missing session token" in exc_info.value.detail
        assert exc_info.value.headers.get("WWW-Authenticate") == "Bearer"

    def test_empty_tokens_raise_401(self):
        with pytest.raises(HTTPException) as exc_info:
            extract_session_token(x_session_id="   ", authorization="")
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Missing session token" in exc_info.value.detail

    def test_malformed_authorization_scheme_raises_401(self):
        with pytest.raises(HTTPException) as exc_info:
            extract_session_token(authorization="Basic dXNlcjpwYXNz")
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Expected 'Bearer <token>'" in exc_info.value.detail

    def test_empty_bearer_token_raises_401(self):
        with pytest.raises(HTTPException) as exc_info:
            extract_session_token(authorization="Bearer ")
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Bearer token is empty" in exc_info.value.detail

    def test_malformed_token_length_raises_401(self):
        with pytest.raises(HTTPException) as exc_info:
            extract_session_token(x_session_id="short_token")
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Malformed session token" in exc_info.value.detail

    def test_malformed_token_characters_raises_401(self):
        with pytest.raises(HTTPException) as exc_info:
            extract_session_token(x_session_id="invalid!chars@in#token$123456789012345")
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Malformed session token" in exc_info.value.detail


class TestFastAPIDependencyIntegration:
    @pytest.fixture
    def test_app(self):
        """Create a minimal FastAPI app with a protected endpoint using the dependency."""
        app = FastAPI()

        @app.get("/test/protected")
        async def protected_endpoint(session_hash: str = Depends(get_current_session_hash)):
            return {
                "success": True,
                "session_hash": session_hash,
            }

        return app

    def test_dependency_never_returns_raw_token(self, test_app):
        """
        SECURITY GUARANTEE:
        The dependency must return ONLY the 64-character SHA-256 session hash,
        NEVER the raw session token.
        """
        client = TestClient(test_app)
        raw_token = create_session_token()
        expected_hash = hash_session_token(raw_token)

        response = client.get("/test/protected", headers={"X-Session-ID": raw_token})
        assert response.status_code == 200
        data = response.json()

        assert data["session_hash"] == expected_hash
        assert data["session_hash"] != raw_token
        assert raw_token not in data.values()

    def test_dependency_via_x_session_id_header(self, test_app):
        client = TestClient(test_app)
        raw_token = create_session_token()
        expected_hash = hash_session_token(raw_token)

        response = client.get("/test/protected", headers={"X-Session-ID": raw_token})
        assert response.status_code == 200
        assert response.json()["session_hash"] == expected_hash

    def test_dependency_via_authorization_bearer_header(self, test_app):
        client = TestClient(test_app)
        raw_token = create_session_token()
        expected_hash = hash_session_token(raw_token)

        response = client.get("/test/protected", headers={"Authorization": f"Bearer {raw_token}"})
        assert response.status_code == 200
        assert response.json()["session_hash"] == expected_hash

    def test_dependency_missing_headers_returns_401(self, test_app):
        client = TestClient(test_app)
        response = client.get("/test/protected")
        assert response.status_code == 401
        assert "Missing session token" in response.json()["detail"]

    def test_dependency_malformed_token_returns_401(self, test_app):
        client = TestClient(test_app)
        response = client.get("/test/protected", headers={"X-Session-ID": "bad_token"})
        assert response.status_code == 401
        assert "Malformed session token" in response.json()["detail"]

    def test_dependency_precedence_verification(self, test_app):
        client = TestClient(test_app)
        token_primary = create_session_token(prefix="abm_s_primary_")
        token_secondary = create_session_token(prefix="abm_s_secondary_")

        expected_hash = hash_session_token(token_primary)
        unexpected_hash = hash_session_token(token_secondary)

        response = client.get(
            "/test/protected",
            headers={
                "X-Session-ID": token_primary,
                "Authorization": f"Bearer {token_secondary}",
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["session_hash"] == expected_hash
        assert data["session_hash"] != unexpected_hash