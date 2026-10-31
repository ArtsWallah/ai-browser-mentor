"""
Session Service for AI Browser Mentor.

Provides cryptographically secure, anonymous session management for multi-user
data isolation on shared backends.

Design Guarantees:
- Server Authority: Tokens are generated with 256 bits of entropy via secrets.token_urlsafe(32).
- Zero Persistence of Raw Tokens: Tokens are immediately hashed with SHA-256.
  Only the 64-character hex digest (session hash) is used for data partitioning.
- Untrusted Client Claims: Client-provided user_id or owner_id claims are never accepted.
  Identity is derived exclusively by hashing the validated session token header.
- Zero Database Dependency: Operates completely in-memory and via cryptographic hashing.
- Explicit Precedence: X-Session-ID takes precedence over Authorization: Bearer <token>.
"""

import hashlib
import logging
import re
import secrets
from typing import Optional
from fastapi import Header, HTTPException, status

logger = logging.getLogger("app.session_service")

# Token Format Configuration
SESSION_TOKEN_PREFIX = "abm_s_"
MIN_TOKEN_LENGTH = 24
MAX_TOKEN_LENGTH = 256
TOKEN_CHAR_REGEX = re.compile(r"^[A-Za-z0-9_-]+$")

HEADER_X_SESSION_ID = "X-Session-ID"
HEADER_AUTHORIZATION = "Authorization"
BEARER_SCHEME = "bearer"


def is_valid_token_format(token: str) -> bool:
    """
    Validate that a session token adheres to length and character-set requirements.
    Only base64url characters [A-Za-z0-9_-] are permitted.
    """
    if not token or not isinstance(token, str):
        return False
    if len(token) < MIN_TOKEN_LENGTH or len(token) > MAX_TOKEN_LENGTH:
        return False
    return bool(TOKEN_CHAR_REGEX.match(token))


def create_session_token(prefix: str = SESSION_TOKEN_PREFIX) -> str:
    """
    Generate a cryptographically secure session token.
    Uses Python's secrets.token_urlsafe(32) to generate 256 bits of entropy.
    """
    raw_entropy = secrets.token_urlsafe(32)
    return f"{prefix}{raw_entropy}" if prefix else raw_entropy


def hash_session_token(token: str) -> str:
    """
    Deterministically hash a session token using SHA-256.
    Returns a 64-character lowercase hexadecimal digest.

    Never logs or persists raw session tokens.
    """
    if token is None or not isinstance(token, str):
        raise ValueError("Session token must be a string")

    clean = token.strip()
    if not clean:
        raise ValueError("Session token cannot be empty or whitespace-only")

    if not is_valid_token_format(clean):
        raise ValueError("Session token format is invalid")

    return hashlib.sha256(clean.encode("utf-8")).hexdigest().lower()


def extract_session_token(
    x_session_id: Optional[str] = None,
    authorization: Optional[str] = None,
) -> str:
    """
    Extract and validate raw session token from headers.

    Precedence Rule:
    `X-Session-ID` is the dedicated header for AI Browser Mentor session tokens
    and takes precedence over `Authorization`.
    - If `X-Session-ID` is provided and non-empty, it is used.
    - If `X-Session-ID` is omitted or empty, `Authorization` is evaluated.

    Raises:
        HTTPException(401): If token is missing, empty, or malformed.
    """
    raw_token: Optional[str] = None

    # 1. Check X-Session-ID first (Precedence)
    if x_session_id is not None and x_session_id.strip() != "":
        raw_token = x_session_id.strip()

    # 2. Check Authorization header fallback
    elif authorization is not None and authorization.strip() != "":
        auth_clean = authorization.strip()
        parts = auth_clean.split(None, 1)

        if len(parts) == 0 or parts[0].lower() != BEARER_SCHEME:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Malformed authorization header. Expected 'Bearer <token>'.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if len(parts) == 1 or not parts[1].strip():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Malformed authorization header. Bearer token is empty.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        raw_token = parts[1].strip()

    # 3. Missing token check
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing session token. Provide X-Session-ID or Authorization: Bearer <token>.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 4. Token format validation
    if not is_valid_token_format(raw_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed session token. Token must contain only URL-safe characters and meet length requirements.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return raw_token


async def get_current_session_hash(
    x_session_id: Optional[str] = Header(None, alias=HEADER_X_SESSION_ID),
    authorization: Optional[str] = Header(None, alias=HEADER_AUTHORIZATION),
) -> str:
    """
    FastAPI dependency that extracts, validates, and hashes the session token.

    Guarantees:
    - Never returns the raw session token.
    - Returns the 64-character SHA-256 digest (session hash).
    - Rejects missing, empty, or malformed tokens with HTTP 401.
    """
    raw_token = extract_session_token(
        x_session_id=x_session_id,
        authorization=authorization,
    )
    return hash_session_token(raw_token)


# Aliases for flexible dependency injection
require_session_hash = get_current_session_hash
get_session_hash = get_current_session_hash
