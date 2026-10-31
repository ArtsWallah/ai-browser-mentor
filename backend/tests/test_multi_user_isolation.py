"""
Phase 2D - Stage 3: Multi-User Page Ownership and Isolation Test Suite

Tests:
1. User A can ingest and retrieve their own page.
2. User B cannot retrieve User A's page.
3. User B cannot query User A's page using /ask or /search.
4. User B cannot execute commands on User A's page.
5. User B cannot summarize or security-analyze User A's page.
6. User B cannot overwrite User A's page using /page or /page/ingest.
7. User B cannot delete or access User A's vector index.
8. Two sessions can use the same page_id without collision.
9. Missing session headers return HTTP 401 on all page endpoints.
10. Unknown and cross-session page IDs return indistinguishable HTTP 404 responses.
11. All page-related endpoints in the inventory enforce authentication.
12. Debug endpoint requires debug token AND additionally enforces session ownership.
"""

import os
import json
import numpy as np
import pytest
from starlette.testclient import TestClient

from app.main import app, page_store, get_page, limiter
from app.services.session_service import create_session_token, hash_session_token
from app.services import vector_store


@pytest.fixture(autouse=True)
def reset_limiter_and_store():
    try:
        limiter.reset()
    except Exception:
        pass
    yield
    try:
        limiter.reset()
    except Exception:
        pass


@pytest.fixture
def session_a():
    token = create_session_token()
    s_hash = hash_session_token(token)
    return {"token": token, "hash": s_hash}


@pytest.fixture
def session_b():
    token = create_session_token()
    s_hash = hash_session_token(token)
    return {"token": token, "hash": s_hash}


@pytest.fixture
def client_a(session_a):
    return TestClient(app, headers={"X-Session-ID": session_a["token"]})


@pytest.fixture
def client_b(session_b):
    return TestClient(app, headers={"X-Session-ID": session_b["token"]})


@pytest.fixture
def client_anon():
    return TestClient(app)


def _make_dummy_page_payload(page_id="test_page_1", title="User A Private Page"):
    return {
        "page_id": page_id,
        "title": title,
        "url": "https://vault.example.com/confidential",
        "hostname": "vault.example.com",
        "description": "Sensitive user data document",
        "headings": ["Confidential Financials", "Employee Secrets"],
        "paragraphs": ["Secret revenue numbers 2026", "Proprietary algorithm code"],
        "chunks": [
            {
                "heading": "Confidential Financials",
                "text": "Secret revenue numbers for 2026 show 10x growth in enterprise sales.",
                "level": 1,
                "type": "section"
            },
            {
                "heading": "Employee Secrets",
                "text": "Proprietary algorithm code uses state machine design pattern.",
                "level": 2,
                "type": "section"
            }
        ],
        "links": [{"index": 0, "text": "Secret Vault", "url": "https://vault.example.com/vault"}],
        "images": [],
        "interactiveElements": [],
        "content": "Secret revenue numbers for 2026 show 10x growth. Proprietary algorithm code.",
        "wordCount": 20
    }


# ============================================================
# 1. VECTOR STORE MULTI-USER ISOLATION TESTS
# ============================================================

class TestVectorStoreMultiUserIsolation:
    def test_vector_store_scoped_keys_differ_for_same_page_id(self, session_a, session_b):
        """Identical page_id in different sessions produces completely distinct filesystem hashes."""
        page_id = "shared_page_id_xyz"
        path_a = vector_store.get_metadata_path(page_id, session_hash=session_a["hash"])
        path_b = vector_store.get_metadata_path(page_id, session_hash=session_b["hash"])
        assert path_a != path_b
        assert os.path.basename(path_a) != os.path.basename(path_b)

    def test_vector_store_user_b_cannot_load_or_search_user_a_index(self, session_a, session_b):
        """Index created by User A cannot be retrieved or searched by User B."""
        page_id = "vector_isolation_test_page"
        embeddings = np.ones((2, 384), dtype="float32")
        chunks = [{"text": "Secret chunk 1"}, {"text": "Secret chunk 2"}]

        # User A creates index
        vector_store.create_index(page_id, embeddings, chunks, session_hash=session_a["hash"])

        # User A can load it
        data_a = vector_store.load_index(page_id, session_hash=session_a["hash"])
        assert data_a is not None
        assert len(data_a["chunks"]) == 2

        # User B CANNOT load it
        data_b = vector_store.load_index(page_id, session_hash=session_b["hash"])
        assert data_b is None

        # User B search returns empty
        query_vec = np.ones((1, 384), dtype="float32")
        results_b = vector_store.search(page_id, query_vec, session_hash=session_b["hash"])
        assert results_b == []

        # Cleanup
        vector_store.delete_index(page_id, session_hash=session_a["hash"])

    def test_vector_store_user_b_cannot_delete_user_a_index(self, session_a, session_b):
        """User B attempting delete_index on User A's page_id does not remove User A's files."""
        page_id = "delete_isolation_test_page"
        embeddings = np.ones((2, 384), dtype="float32")
        chunks = [{"text": "Indelible data"}]

        vector_store.create_index(page_id, embeddings, chunks, session_hash=session_a["hash"])

        # User B attempts to delete
        deleted_by_b = vector_store.delete_index(page_id, session_hash=session_b["hash"])
        assert deleted_by_b is False

        # User A's data remains intact
        data_a = vector_store.load_index(page_id, session_hash=session_a["hash"])
        assert data_a is not None

        # Cleanup by actual owner
        vector_store.delete_index(page_id, session_hash=session_a["hash"])

    def test_vector_store_unowned_legacy_not_adopted_by_session(self, session_a):
        """A session lookup never transparently adopts or exposes unowned legacy files."""
        legacy_id = "legacy_unowned_canary_page"
        legacy_meta = vector_store._get_legacy_metadata_path(legacy_id)
        assert legacy_meta is not None
        with open(legacy_meta, "w", encoding="utf-8") as f:
            f.write(json.dumps({"page_id": legacy_id, "chunks": [{"text": "unowned legacy secret"}]}))

        try:
            # When session_hash is provided, it must NOT fall back to the unowned legacy file
            data = vector_store.load_index(legacy_id, session_hash=session_a["hash"])
            assert data is None

            meta = vector_store.get_metadata(legacy_id, session_hash=session_a["hash"])
            assert meta is None
        finally:
            if os.path.exists(legacy_meta):
                os.remove(legacy_meta)


# ============================================================
# 2. API MULTI-USER ISOLATION TESTS
# ============================================================

class TestApiMultiUserOwnershipEnforcement:
    def test_user_a_can_ingest_and_retrieve_own_page(self, client_a, session_a):
        """User A ingests page and can access it."""
        page_id = "user_a_page_roundtrip"
        payload = _make_dummy_page_payload(page_id=page_id)

        res = client_a.post("/page/ingest", json=payload)
        assert res.status_code == 200
        assert res.json().get("page_id") == page_id

        # Verify page is in store under session_a
        page = get_page(session_a["hash"], page_id)
        assert page is not None
        assert page.get("title") == payload["title"]

    def test_user_b_cannot_retrieve_user_a_page(self, client_a, client_b, session_a, session_b):
        """User B cannot access User A's page via storage or API."""
        page_id = "user_a_private_page_404"
        payload = _make_dummy_page_payload(page_id=page_id)

        # Ingest as User A
        res_a = client_a.post("/page/ingest", json=payload)
        assert res_a.status_code == 200

        # Storage layer isolation check
        assert get_page(session_a["hash"], page_id) is not None
        assert get_page(session_b["hash"], page_id) is None

    def test_user_b_cannot_query_user_a_page_via_ask_or_search(self, client_a, client_b):
        """User B querying User A's page_id via /ask or /search receives HTTP 404."""
        page_id = "user_a_query_target"
        payload = _make_dummy_page_payload(page_id=page_id)
        res_ingest = client_a.post("/page/ingest", json=payload)
        assert res_ingest.status_code == 200

        # User B queries /search
        res_search = client_b.post("/search", json={"query": "financials", "page_id": page_id, "top_k": 5})
        assert res_search.status_code == 404
        assert "Page not found" in res_search.json().get("detail", "")

        # User B queries /ask
        res_ask = client_b.post("/ask", json={"question": "What are the revenue numbers?", "page_id": page_id})
        assert res_ask.status_code == 404
        assert "Page not found" in res_ask.json().get("detail", "")

    def test_user_b_cannot_execute_commands_on_user_a_page(self, client_a, client_b):
        """User B attempting /command/execute or /assistant/command on User A's page receives HTTP 404."""
        page_id = "user_a_command_target"
        payload = _make_dummy_page_payload(page_id=page_id)
        res_ingest = client_a.post("/page/ingest", json=payload)
        assert res_ingest.status_code == 200

        cmd_payload = {
            "instruction": "Summarize this page",
            "intent": "summarize_page",
            "page_id": page_id,
            "selection_text": "",
            "page_url": "https://vault.example.com",
            "page_title": "Confidential",
            "privacy_mode": "hybrid"
        }

        # User B calls /command/execute
        res_cmd = client_b.post("/command/execute", json=cmd_payload)
        assert res_cmd.status_code == 404
        assert "Page not found" in res_cmd.json().get("detail", "")

        # User B calls /assistant/command
        res_asst = client_b.post("/assistant/command", json=cmd_payload)
        assert res_asst.status_code == 404

        # User B calls /assistant/query
        res_query = client_b.post("/assistant/query", json={"query": "summarize", "page_id": page_id, "mode": "summary"})
        assert res_query.status_code == 404

    def test_user_b_cannot_summarize_or_security_analyze_user_a_page(self, client_a, client_b):
        """User B attempting /page/summary or /security/analyze-page receives HTTP 404."""
        page_id = "user_a_summary_target"
        payload = _make_dummy_page_payload(page_id=page_id)
        client_a.post("/page/ingest", json=payload)

        # /page/summary
        res_summary = client_b.post("/page/summary", json={"page_id": page_id})
        assert res_summary.status_code == 404

        # /security/analyze-page
        res_sec = client_b.post("/security/analyze-page", json={"page_id": page_id})
        assert res_sec.status_code == 404

    def test_user_b_cannot_overwrite_user_a_page(self, client_a, client_b, session_a, session_b):
        """Two users ingesting identical page_id maintain strictly isolated, non-colliding records."""
        shared_page_id = "collision_test_page_123"
        payload_a = _make_dummy_page_payload(page_id=shared_page_id, title="User A Original Title")
        payload_b = _make_dummy_page_payload(page_id=shared_page_id, title="User B Malicious Overwrite")

        # User A ingests first
        res_a = client_a.post("/page/ingest", json=payload_a)
        assert res_a.status_code == 200

        # User B ingests with same page_id
        res_b = client_b.post("/page/ingest", json=payload_b)
        assert res_b.status_code == 200

        # User A's page is UNCHANGED
        page_a = get_page(session_a["hash"], shared_page_id)
        assert page_a is not None
        assert page_a["title"] == "User A Original Title"

        # User B's page contains User B's data
        page_b = get_page(session_b["hash"], shared_page_id)
        assert page_b is not None
        assert page_b["title"] == "User B Malicious Overwrite"

        # Same test for /page compatibility endpoint
        client_b.post("/page", json={"page_id": shared_page_id, "title": "Overwritten by /page endpoint"})
        page_a_after = get_page(session_a["hash"], shared_page_id)
        assert page_a_after["title"] == "User A Original Title"

    def test_missing_session_headers_return_401_on_all_page_endpoints(self, client_anon):
        """All page endpoints in the inventory reject unauthenticated calls with HTTP 401."""
        endpoints = [
            ("POST", "/page/ingest", {"title": "Test"}),
            ("POST", "/page", {"page_id": "test"}),
            ("POST", "/ask", {"question": "q", "page_id": "p"}),
            ("POST", "/command/execute", {"instruction": "ins"}),
            ("POST", "/assistant/command", {"instruction": "ins"}),
            ("POST", "/assistant/query", {"query": "q"}),
            ("POST", "/page/summary", {"page_id": "p"}),
            ("POST", "/security/analyze-page", {"page_id": "p"}),
            ("POST", "/search", {"query": "q", "page_id": "p"}),
            ("POST", "/scan-links", {"links": []}),
        ]

        for method, endpoint, body in endpoints:
            if method == "POST":
                res = client_anon.post(endpoint, json=body)
            else:
                res = client_anon.get(endpoint)
            assert res.status_code == 401, f"Endpoint {method} {endpoint} must return 401 without session header, got {res.status_code}"

    def test_unknown_and_cross_session_page_ids_return_identical_404(self, client_a, client_b):
        """Nonexistent page_id and cross-session page_id return indistinguishable HTTP 404 responses."""
        real_page_id = "real_existing_user_a_page"
        client_a.post("/page/ingest", json=_make_dummy_page_payload(page_id=real_page_id))

        nonexistent_page_id = "completely_fictitious_page_999"

        # Cross-session request
        res_cross = client_b.post("/page/summary", json={"page_id": real_page_id})
        # Nonexistent request
        res_nonexistent = client_b.post("/page/summary", json={"page_id": nonexistent_page_id})

        assert res_cross.status_code == 404
        assert res_nonexistent.status_code == 404
        assert res_cross.json() == res_nonexistent.json()

    def test_debug_endpoint_enforces_both_debug_token_and_ownership(self, client_a, client_b, session_a, session_b, monkeypatch):
        """GET /debug/pages/{page_id} requires debug token AND verifies session ownership."""
        monkeypatch.setenv("DEBUG_ACCESS_TOKEN", "super-secret-debug-pass")
        from app import main as main_module
        monkeypatch.setattr(main_module, "DEBUG_ACCESS_TOKEN", "super-secret-debug-pass")

        page_id = "debug_ownership_test_page"
        client_a.post("/page/ingest", json=_make_dummy_page_payload(page_id=page_id))

        # Case 1: Missing debug token -> 401
        res_no_debug = client_a.get(f"/debug/pages/{page_id}")
        assert res_no_debug.status_code == 401

        # Case 2: Wrong debug token -> 403
        res_bad_debug = client_a.get(f"/debug/pages/{page_id}", headers={"X-Debug-Token": "wrong-token"})
        assert res_bad_debug.status_code == 403

        # Case 3: Valid debug token + Owner session -> 200
        res_owner = client_a.get(
            f"/debug/pages/{page_id}",
            headers={"X-Debug-Token": "super-secret-debug-pass"}
        )
        assert res_owner.status_code == 200
        assert res_owner.json()["page"]["page_id"] == page_id

        # Case 4: Valid debug token + Non-owner session -> 404 (does not leak other users' pages)
        res_non_owner = client_b.get(
            f"/debug/pages/{page_id}",
            headers={"X-Debug-Token": "super-secret-debug-pass"}
        )
        assert res_non_owner.status_code == 404

    def test_scan_links_ownership_enforcement(self, client_a, client_b):
        """POST /scan-links with page_id enforces session ownership."""
        page_id = "scan_links_target_page"
        client_a.post("/page/ingest", json=_make_dummy_page_payload(page_id=page_id))

        # Owner scans links by page_id
        res_owner = client_a.post("/scan-links", json={"page_id": page_id, "links": []})
        assert res_owner.status_code == 200

        # Non-owner scans links by page_id -> 404
        res_non_owner = client_b.post("/scan-links", json={"page_id": page_id, "links": []})
        assert res_non_owner.status_code == 404

    def test_page_compatibility_endpoint_dual_ownership(self, client_a, client_b, session_a, session_b):
        """POST /page: User A registers a page; User A can access it; User B cannot read or overwrite it."""
        page_id = "page_compat_dual_test"
        payload_a = {
            "page_id": page_id,
            "title": "User A Secret Document",
            "url": "https://vault.example.com/doc_a",
            "chunks": [{"id": 1, "heading": "Classified", "text": "Top secret plan Alpha"}],
            "links": [],
            "interactiveElements": []
        }

        # 1. User A registers via /page
        res_a = client_a.post("/page", json=payload_a)
        assert res_a.status_code == 200
        assert res_a.json()["page_id"] == page_id

        # User A can query it via /search
        res_search_a = client_a.post("/search", json={"query": "secret plan", "page_id": page_id})
        assert res_search_a.status_code == 200
        assert len(res_search_a.json()["results"]) > 0

        # 2. User B cannot access it via /search -> 404
        res_search_b = client_b.post("/search", json={"query": "secret plan", "page_id": page_id})
        assert res_search_b.status_code == 404

        # 3. User B cannot access it via /page/summary -> 404
        res_sum_b = client_b.post("/page/summary", json={"page_id": page_id})
        assert res_sum_b.status_code == 404

        # 4. User B registering same page_id does NOT overwrite User A's data
        payload_b = {
            "page_id": page_id,
            "title": "User B Separate Doc",
            "url": "https://vault.example.com/doc_b",
            "chunks": [{"id": 1, "heading": "Public", "text": "Public plan Beta"}]
        }
        res_b = client_b.post("/page", json=payload_b)
        assert res_b.status_code == 200

        # User A's document in store is completely unaltered
        page_a = get_page(session_a["hash"], page_id)
        assert page_a["title"] == "User A Secret Document"
        assert page_a["chunks"][0]["text"] == "Top secret plan Alpha"

        # User B's document in store has User B's content
        page_b = get_page(session_b["hash"], page_id)
        assert page_b["title"] == "User B Separate Doc"
        assert page_b["chunks"][0]["text"] == "Public plan Beta"

    def test_search_endpoint_dual_ownership(self, client_a, client_b):
        """POST /search: User A succeeds with 200 and results; User B receives 404 on User A's page_id."""
        page_id = "search_dual_test_page"
        client_a.post("/page/ingest", json=_make_dummy_page_payload(page_id=page_id))

        # User A searches own page -> 200 with matching chunks
        res_a = client_a.post("/search", json={"query": "revenue", "page_id": page_id, "top_k": 3})
        assert res_a.status_code == 200
        data_a = res_a.json()
        assert data_a["success"] is True
        assert len(data_a["results"]) > 0
        assert "revenue" in data_a["results"][0]["document"]["text"].lower()

        # User B searches User A's page -> 404
        res_b = client_b.post("/search", json={"query": "revenue", "page_id": page_id, "top_k": 3})
        assert res_b.status_code == 404
        assert res_b.json()["detail"] == "Page not found. Read the current page first."

    def test_ask_endpoint_dual_ownership(self, client_a, client_b):
        """POST /ask: User A succeeds with 200 and answer; User B receives 404 on User A's page_id."""
        page_id = "ask_dual_test_page"
        client_a.post("/page/ingest", json=_make_dummy_page_payload(page_id=page_id))

        # User A asks question on own page -> 200
        res_a = client_a.post("/ask", json={"question": "What are the revenue projections?", "page_id": page_id})
        assert res_a.status_code == 200
        data_a = res_a.json()
        assert data_a["success"] is True
        assert len(data_a.get("answer", "")) > 0

        # User B asks question on User A's page -> 404
        res_b = client_b.post("/ask", json={"question": "What are the revenue projections?", "page_id": page_id})
        assert res_b.status_code == 404
        assert res_b.json()["detail"] == "Page not found. Please read the current page first."

    def test_assistant_query_endpoint_dual_ownership(self, client_a, client_b):
        """POST /assistant/query: User A succeeds with 200; User B receives 404 on User A's page_id."""
        page_id = "asst_query_dual_test_page"
        client_a.post("/page/ingest", json=_make_dummy_page_payload(page_id=page_id))

        # User A queries own page -> 200
        res_a = client_a.post("/assistant/query", json={
            "query": "summarize this page",
            "page_id": page_id,
            "mode": "summary"
        })
        assert res_a.status_code == 200
        data_a = res_a.json()
        assert data_a["success"] is True

        # User B queries User A's page -> 404
        res_b = client_b.post("/assistant/query", json={
            "query": "summarize this page",
            "page_id": page_id,
            "mode": "summary"
        })
        assert res_b.status_code == 404
        assert res_b.json()["detail"] == "Page not found. Please read page first."

    def test_assistant_command_endpoint_dual_ownership(self, client_a, client_b):
        """POST /assistant/command: User A succeeds with 200; User B receives 404 on User A's page_id."""
        page_id = "asst_cmd_dual_test_page"
        client_a.post("/page/ingest", json=_make_dummy_page_payload(page_id=page_id))

        # User A issues command on own page -> 200
        res_a = client_a.post("/assistant/command", json={
            "instruction": "Summarize this page",
            "page_id": page_id
        })
        assert res_a.status_code == 200
        data_a = res_a.json()
        assert data_a["success"] is True

        # User B issues command on User A's page -> 404
        res_b = client_b.post("/assistant/command", json={
            "instruction": "Summarize this page",
            "page_id": page_id
        })
        assert res_b.status_code == 404
        assert res_b.json()["detail"] == "Page not found. Please read page first."

    def test_command_execute_endpoint_dual_ownership(self, client_a, client_b):
        """POST /command/execute: User A succeeds with 200; User B receives 404 on User A's page_id."""
        page_id = "cmd_exec_dual_test_page"
        client_a.post("/page/ingest", json=_make_dummy_page_payload(page_id=page_id))

        # User A executes command on own page -> 200
        res_a = client_a.post("/command/execute", json={
            "instruction": "Extract page information and outline",
            "page_id": page_id
        })
        assert res_a.status_code == 200
        data_a = res_a.json()
        assert data_a["success"] is True

        # User B executes command on User A's page -> 404
        res_b = client_b.post("/command/execute", json={
            "instruction": "Extract page information and outline",
            "page_id": page_id
        })
        assert res_b.status_code == 404
        assert res_b.json()["detail"] == "Page not found. Please read page first."

    def test_page_summary_endpoint_dual_ownership(self, client_a, client_b):
        """POST /page/summary: User A succeeds with 200; User B receives 404 on User A's page_id."""
        page_id = "summary_dual_test_page"
        client_a.post("/page/ingest", json=_make_dummy_page_payload(page_id=page_id))

        # User A requests summary -> 200
        res_a = client_a.post("/page/summary", json={"page_id": page_id})
        assert res_a.status_code == 200
        data_a = res_a.json()
        assert data_a["success"] is True

        # User B requests summary on User A's page -> 404
        res_b = client_b.post("/page/summary", json={"page_id": page_id})
        assert res_b.status_code == 404
        assert res_b.json()["detail"] == "Page not found. Please read page first."

    def test_security_analyze_page_dual_ownership(self, client_a, client_b):
        """POST /security/analyze-page: User A succeeds with 200; User B receives 404 on User A's page_id."""
        page_id = "security_dual_test_page"
        client_a.post("/page/ingest", json=_make_dummy_page_payload(page_id=page_id))

        # User A requests security analysis -> 200
        res_a = client_a.post("/security/analyze-page", json={"page_id": page_id})
        assert res_a.status_code == 200
        data_a = res_a.json()
        assert "risk_score" in data_a or "riskLevel" in data_a or "heuristic_indicators" in data_a

        # User B requests security analysis on User A's page -> 404
        res_b = client_b.post("/security/analyze-page", json={"page_id": page_id})
        assert res_b.status_code == 404
        assert res_b.json()["detail"] == "Page not found. Please read page first."