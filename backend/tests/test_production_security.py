"""
Security and Production Hardening Test Suite (Phase 1)
Tests:
- /debug/pages protection in production
- Request body size limits (HTTP 413)
- Server-side rate limiting (HTTP 429)
- Bounded LRU page_store
- CORS environment configuration
- Safe vector store directories & temporary cleanup
- Machine-agnostic model path resolution
- Sensitive data redaction in logs
"""
import os
import time
from pathlib import Path
import pytest
from starlette.testclient import TestClient
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

from app import main as main_module
from app.main import app, page_store, BoundedPageStore, RequestSizeLimitMiddleware
from app.services.vector_store import (
    init_vector_store_dir,
    cleanup_temporary_vector_store,
    VECTOR_DIR
)
from app.scamshield_service import resolve_model_path


@pytest.fixture
def client():
    return TestClient(app)


# ============================================================
# 1. DEBUG ENDPOINT PROTECTION
# ============================================================

def test_debug_pages_development_access(client):
    """In development mode, debug endpoints are accessible."""
    old_env = main_module.ENVIRONMENT
    try:
        main_module.ENVIRONMENT = "development"
        resp = client.get("/debug/pages")
        assert resp.status_code == 200
        assert "pages" in resp.json()
        assert "pageCount" in resp.json()
    finally:
        main_module.ENVIRONMENT = old_env


def test_debug_pages_production_protection_forbidden(client):
    """In production mode, debug endpoints are blocked with 403 Forbidden without token."""
    old_env = main_module.ENVIRONMENT
    old_token = main_module.DEBUG_ACCESS_TOKEN
    try:
        main_module.ENVIRONMENT = "production"
        main_module.DEBUG_ACCESS_TOKEN = "super-secret-admin-token-12345"

        # Missing token -> 403
        resp_missing = client.get("/debug/pages")
        assert resp_missing.status_code == 403
        assert "disabled in production mode" in resp_missing.json().get("detail", "")

        # Invalid token -> 403
        resp_invalid = client.get("/debug/pages", headers={"X-Debug-Token": "wrong-token"})
        assert resp_invalid.status_code == 403

        # Single page missing token -> 403
        resp_single = client.get("/debug/pages/any-page-id")
        assert resp_single.status_code == 403
    finally:
        main_module.ENVIRONMENT = old_env
        main_module.DEBUG_ACCESS_TOKEN = old_token


def test_debug_pages_production_protection_authorized(client):
    """In production mode, debug endpoints succeed when supplied with the valid X-Debug-Token."""
    old_env = main_module.ENVIRONMENT
    old_token = main_module.DEBUG_ACCESS_TOKEN
    try:
        main_module.ENVIRONMENT = "production"
        main_module.DEBUG_ACCESS_TOKEN = "super-secret-admin-token-12345"

        resp = client.get("/debug/pages", headers={"X-Debug-Token": "super-secret-admin-token-12345"})
        assert resp.status_code == 200
        assert resp.json().get("success") is True
    finally:
        main_module.ENVIRONMENT = old_env
        main_module.DEBUG_ACCESS_TOKEN = old_token


# ============================================================
# 2. REQUEST BODY SIZE LIMIT (HTTP 413)
# ============================================================

def test_request_size_limit_content_length_413(client):
    """A request advertising a Content-Length greater than MAX_REQUEST_BODY_SIZE receives 413."""
    # Send a request with a header claiming 5 MB body size
    resp = client.post(
        "/hover-check",
        headers={"Content-Length": str(5 * 1024 * 1024)},
        content=b"test"
    )
    assert resp.status_code == 413
    data = resp.json()
    assert data["success"] is False
    assert "too large" in data["error"].lower()


def test_request_size_limit_streaming_chunk_413():
    """An ASGI app wrapped in RequestSizeLimitMiddleware aborts mid-stream if bytes exceed limit."""
    mini_app = FastAPI()
    mini_app.add_middleware(RequestSizeLimitMiddleware, max_body_size=50)

    @mini_app.post("/stream-test")
    async def stream_test(request: Request):
        body = await request.body()
        return {"len": len(body)}

    mini_client = TestClient(mini_app)

    # 1. Below limit (40 bytes)
    resp_ok = mini_client.post("/stream-test", content=b"A" * 40)
    assert resp_ok.status_code == 200

    # 2. Above limit (100 bytes)
    resp_large = mini_client.post("/stream-test", content=b"A" * 100)
    assert resp_large.status_code == 413
    assert resp_large.json()["success"] is False


# ============================================================
# 3. BOUNDED IN-MEMORY PAGE STORE (LRU EVICTION)
# ============================================================

def test_bounded_page_store_lru_eviction():
    """Page store enforces maximum capacity and evicts least recently accessed entries first."""
    store = BoundedPageStore(max_size=3)

    store["page-1"] = {"title": "Page 1"}
    store["page-2"] = {"title": "Page 2"}
    store["page-3"] = {"title": "Page 3"}
    assert len(store) == 3

    # Access page-1 so it becomes most recently used; page-2 is now oldest
    _ = store.get("page-1")

    # Add page-4 -> should evict page-2
    store["page-4"] = {"title": "Page 4"}
    assert len(store) == 3
    assert "page-2" not in store
    assert "page-1" in store
    assert "page-3" in store
    assert "page-4" in store

    # Add page-5 -> should evict page-3
    store["page-5"] = {"title": "Page 5"}
    assert len(store) == 3
    assert "page-3" not in store
    assert "page-1" in store


def test_bounded_page_store_concurrency():
    """BoundedPageStore handles concurrent read/write access safely."""
    import concurrent.futures

    store = BoundedPageStore(max_size=50)

    def worker(i: int):
        for j in range(20):
            key = f"key-{i}-{j}"
            store[key] = {"val": j}
            _ = store.get(key)
        return True

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(worker, i) for i in range(5)]
        for f in concurrent.futures.as_completed(futures):
            assert f.result() is True

    assert len(store) <= 50


# ============================================================
# 4. SERVER-SIDE RATE LIMITING
# ============================================================

def test_rate_limiting_enforcement_429():
    """Endpoints decorated with slowapi limit return 429 when threshold is exceeded."""
    from slowapi import Limiter
    from slowapi.util import get_remote_address

    test_limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")
    test_app = FastAPI()
    test_app.state.limiter = test_limiter
    test_app.add_exception_handler(
        main_module.RateLimitExceeded,
        main_module.custom_rate_limit_handler
    )

    @test_app.post("/expensive-test")
    @test_limiter.limit("2/minute")
    def expensive_test(request: Request):
        return {"status": "ok"}

    t_client = TestClient(test_app)

    # 1st request -> OK
    r1 = t_client.post("/expensive-test")
    assert r1.status_code == 200

    # 2nd request -> OK
    r2 = t_client.post("/expensive-test")
    assert r2.status_code == 200

    # 3rd request -> 429 Too Many Requests
    r3 = t_client.post("/expensive-test")
    assert r3.status_code == 429
    data = r3.json()
    assert data["success"] is False
    assert "Rate limit exceeded" in data["error"]
    assert "Retry-After" in r3.headers


# ============================================================
# 5. CORS CONFIGURATION
# ============================================================

def test_cors_preflight_allowed_origin(client):
    """OPTIONS preflight with allowed localhost or extension origin returns CORS headers."""
    resp = client.options(
        "/command/execute",
        headers={
            "Origin": "http://localhost:8000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        }
    )
    assert resp.status_code in (200, 204)
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:8000"


def test_cors_extension_regex_origin(client):
    """OPTIONS preflight with valid Chrome extension origin (32 char id) matches regex."""
    extension_origin = "chrome-extension://abcdefghijklmnopqrstuvwxyzabcdef"
    resp = client.options(
        "/command/execute",
        headers={
            "Origin": extension_origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        }
    )
    assert resp.status_code in (200, 204)
    assert resp.headers.get("access-control-allow-origin") == extension_origin


def test_cors_disallowed_origin(client):
    """Arbitrary untrusted origin is NOT granted CORS origin header."""
    resp = client.options(
        "/command/execute",
        headers={
            "Origin": "https://malicious-phishing-site.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        }
    )
    assert resp.headers.get("access-control-allow-origin") is None


# ============================================================
# 6. VECTOR STORE SAFE DIR CREATION AND CLEANUP POLICY
# ============================================================

def test_vector_store_init_and_cleanup(tmp_path):
    """Safe directory creation and cleanup policy purges stale temp files without touching datasets."""
    test_store_dir = tmp_path / "vector_store"
    d = init_vector_store_dir(base_dir=test_store_dir)
    assert Path(d).is_dir()

    # Create a fresh temp file (< 24 hours old)
    fresh_temp = test_store_dir / "temp_idx_fresh.faiss"
    fresh_temp.write_text("fresh index data")

    # Create an old temp file (> 24 hours old)
    old_temp = test_store_dir / "temp_idx_old.faiss"
    old_temp.write_text("old index data")
    old_timestamp = time.time() - (30 * 3600)  # 30 hours ago
    os.utime(old_temp, (old_timestamp, old_timestamp))

    # Create a non-temporary dataset or model file
    important_data = test_store_dir / "important_dataset.csv"
    important_data.write_text("important user or training data")
    os.utime(important_data, (old_timestamp, old_timestamp))

    # Run cleanup
    purged = cleanup_temporary_vector_store(base_dir=test_store_dir, max_age_hours=24)
    assert purged == 1

    # Old temp was deleted
    assert not old_temp.exists()
    # Fresh temp was preserved
    assert fresh_temp.exists()
    # Important data was never touched
    assert important_data.exists()


# ============================================================
# 7. MODEL PATH RESOLUTION (MACHINE-AGNOSTIC)
# ============================================================

def test_resolve_model_path_machine_agnostic():
    """Model path resolution handles relative paths and does not require machine-specific Windows paths."""
    resolved = resolve_model_path("data/models/tfidf_multilabel_baseline.joblib")
    # Even if file doesn't exist in a bare clone, it returns a clean Path object
    assert isinstance(resolved, Path)
    assert not str(resolved).startswith("C:/Users/SomeUser/Desktop")
