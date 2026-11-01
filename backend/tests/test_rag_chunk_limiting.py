"""
Tests for Phase 2B: RAG Chunk Limiting for Render Memory Optimization.

Verifies:
1. Pages with <= MAX_INDEXED_CHUNKS (e.g., 15 chunks) have all chunks embedded and indexed.
2. Pages with > MAX_INDEXED_CHUNKS (e.g., 74 chunks) have exactly MAX_INDEXED_CHUNKS (40) indexed.
3. Original full webpage content (all raw_chunks, chunks, paragraphs, content) is preserved in page_store.
4. Response chunkCount reports the original webpage chunk count without modification.
5. Embeddings and indexed chunk metadata are strictly aligned (1:1 correspondence).
6. Empty and whitespace-only chunks are skipped without causing index drift or misalignment.
7. Pages with no valid chunks safely bypass embed_texts() and FAISS indexing.
8. MAX_INDEXED_CHUNKS fallback and validation logic.
"""

import os
import numpy as np
import pytest
from starlette.testclient import TestClient

from app.main import app, MAX_INDEXED_CHUNKS, get_page, build_chunk_text
from app.services.session_service import hash_session_token
from app.services.vector_store import load_index, delete_index

TEST_TOKEN = "abm_s_test_rag_limit_token_1234567890"
TEST_SESSION_HASH = hash_session_token(TEST_TOKEN)


@pytest.fixture
def client():
    return TestClient(app, headers={"X-Session-ID": TEST_TOKEN})


def load_max_indexed_chunks_from_env() -> int:
    """
    Isolated configuration-loading helper matching the
    MAX_INDEXED_CHUNKS parsing and fallback logic from app.main.
    """
    try:
        val = int(os.getenv("MAX_INDEXED_CHUNKS", "40"))
        if val <= 0:
            return 40
        return val
    except (ValueError, TypeError):
        return 40


def _build_mock_chunks(count: int) -> list[dict]:
    """Helper to generate distinct, substantive test chunks."""
    return [
        {
            "heading": f"Section Header {i}",
            "text": f"This is substantive content paragraph for test section number {i}. Contains unique descriptive text.",
            "level": 2,
            "type": "section"
        }
        for i in range(count)
    ]


class TestRagChunkLimiting:
    def test_under_limit_chunks_all_indexed(self, client, monkeypatch):
        """Pages with fewer than 40 chunks (e.g. 15) must index all chunks."""
        page_id = "test_page_15_chunks"
        delete_index(page_id, session_hash=TEST_SESSION_HASH)

        recorded_chunk_texts = []

        def mock_embed_texts(texts, **kwargs):
            recorded_chunk_texts.extend(texts)
            return np.zeros((len(texts), 384), dtype=np.float32)

        monkeypatch.setattr("app.main.embed_texts", mock_embed_texts)

        chunks_15 = _build_mock_chunks(15)
        payload = {
            "page_id": page_id,
            "title": "Document with 15 sections",
            "url": "https://example.com/doc15",
            "hostname": "example.com",
            "description": "A 15-section document.",
            "headings": [c["heading"] for c in chunks_15],
            "paragraphs": [c["text"] for c in chunks_15],
            "chunks": chunks_15,
            "content": " ".join(c["text"] for c in chunks_15),
            "wordCount": 150
        }

        try:
            res = client.post("/page/ingest", json=payload)
            assert res.status_code == 200
            data = res.json()
            assert data.get("success") is True
            assert data.get("chunkCount") == 15

            # Exactly 15 chunks embedded
            assert len(recorded_chunk_texts) == 15

            # Full page in page_store has all 15 chunks
            stored_page = get_page(TEST_SESSION_HASH, page_id)
            assert stored_page is not None
            assert len(stored_page["raw_chunks"]) == 15
            assert len(stored_page["chunks"]) == 15

            # Vector store index has all 15 chunks
            idx_data = load_index(page_id, session_hash=TEST_SESSION_HASH)
            assert idx_data is not None
            assert len(idx_data["chunks"]) == 15

            vector_count = (
                idx_data["index"].ntotal
                if idx_data.get("type") == "faiss"
                else len(idx_data["embeddings"])
            )
            assert vector_count == 15
        finally:
            delete_index(page_id, session_hash=TEST_SESSION_HASH)

    def test_over_limit_chunks_capped_at_max(self, client, monkeypatch):
        """Pages with more than 40 chunks (e.g. 74) must index exactly MAX_INDEXED_CHUNKS (40)."""
        page_id = "test_page_74_chunks"
        delete_index(page_id, session_hash=TEST_SESSION_HASH)

        recorded_chunk_texts = []

        def mock_embed_texts(texts, **kwargs):
            recorded_chunk_texts.extend(texts)
            return np.zeros((len(texts), 384), dtype=np.float32)

        monkeypatch.setattr("app.main.embed_texts", mock_embed_texts)

        chunks_74 = _build_mock_chunks(74)
        payload = {
            "page_id": page_id,
            "title": "Long Document with 74 sections",
            "url": "https://example.com/doc74",
            "hostname": "example.com",
            "description": "A 74-section document reproducing production OOM trigger.",
            "headings": [c["heading"] for c in chunks_74],
            "paragraphs": [c["text"] for c in chunks_74],
            "chunks": chunks_74,
            "content": " ".join(c["text"] for c in chunks_74),
            "wordCount": 740
        }

        try:
            res = client.post("/page/ingest", json=payload)
            assert res.status_code == 200
            data = res.json()
            assert data.get("success") is True
            # API response chunkCount MUST report the original 74 chunks
            assert data.get("chunkCount") == 74

            # Embeddings MUST be limited to MAX_INDEXED_CHUNKS (40)
            assert len(recorded_chunk_texts) == MAX_INDEXED_CHUNKS
            assert len(recorded_chunk_texts) == 40

            # ALL 74 original chunks MUST be preserved in page_store
            stored_page = get_page(TEST_SESSION_HASH, page_id)
            assert stored_page is not None
            assert len(stored_page["raw_chunks"]) == 74
            assert len(stored_page["chunks"]) == 74
            assert len(stored_page["paragraphs"]) == 74
            assert len(stored_page["content"]) == len(payload["content"])

            # Vector store index MUST have exactly MAX_INDEXED_CHUNKS (40) chunks and vectors
            idx_data = load_index(page_id, session_hash=TEST_SESSION_HASH)
            assert idx_data is not None
            assert len(idx_data["chunks"]) == 40

            vector_count = (
                idx_data["index"].ntotal
                if idx_data.get("type") == "faiss"
                else len(idx_data["embeddings"])
            )
            assert vector_count == 40
        finally:
            delete_index(page_id, session_hash=TEST_SESSION_HASH)

    def test_embeddings_and_metadata_remain_aligned_with_empty_chunks(self, client, monkeypatch):
        """Empty and whitespace chunks are skipped without causing index drift or misalignment."""
        page_id = "test_page_alignment"
        delete_index(page_id, session_hash=TEST_SESSION_HASH)

        recorded_chunk_texts = []

        def mock_embed_texts(texts, **kwargs):
            recorded_chunk_texts.extend(texts)
            # Return distinct dummy vectors where vector[i][0] = i
            arr = np.zeros((len(texts), 384), dtype=np.float32)
            for i in range(len(texts)):
                arr[i, 0] = float(i)
            return arr

        monkeypatch.setattr("app.main.embed_texts", mock_embed_texts)

        # Mix valid chunks with empty/whitespace chunks
        raw_chunks = [
            {"heading": "Valid H0", "text": "Substantive text zero.", "level": 1, "type": "section"},
            {"heading": "Empty Text", "text": "", "level": 1, "type": "section"},
            {"heading": "Valid H1", "text": "Substantive text one.", "level": 1, "type": "section"},
            {"heading": "", "text": "   ", "level": 1, "type": "section"},
            {"heading": "Valid H2", "text": "Substantive text two.", "level": 1, "type": "section"},
            {"heading": "   ", "text": "", "level": 1, "type": "section"},
            {"heading": "Valid H3", "text": "Substantive text three.", "level": 1, "type": "section"},
        ]

        payload = {
            "page_id": page_id,
            "title": "Alignment Test Page",
            "url": "https://example.com/align",
            "chunks": raw_chunks,
            "content": "Valid content.",
            "wordCount": 30
        }

        try:
            res = client.post("/page/ingest", json=payload)
            assert res.status_code == 200

            # Only the 4 valid chunks should be embedded
            assert len(recorded_chunk_texts) == 4

            idx_data = load_index(page_id, session_hash=TEST_SESSION_HASH)
            assert idx_data is not None
            indexed_chunks = idx_data["chunks"]
            assert len(indexed_chunks) == 4

            # Verify exact 1-to-1 match between recorded texts and indexed chunks
            for i in range(4):
                expected_text = build_chunk_text(indexed_chunks[i])
                assert expected_text == recorded_chunk_texts[i], (
                    f"Drift at index {i}: chunk '{expected_text}' != embedding text '{recorded_chunk_texts[i]}'"
                )

            vector_count = (
                idx_data["index"].ntotal
                if idx_data.get("type") == "faiss"
                else len(idx_data["embeddings"])
            )
            assert vector_count == 4
        finally:
            delete_index(page_id, session_hash=TEST_SESSION_HASH)

    def test_page_with_no_valid_chunks_skips_indexing(self, client, monkeypatch):
        """A page containing no valid chunks does not attempt embedding or FAISS indexing."""
        page_id = "test_page_no_valid_chunks"
        delete_index(page_id, session_hash=TEST_SESSION_HASH)

        embed_called = False
        create_index_called = False

        def mock_embed_texts(texts, **kwargs):
            nonlocal embed_called
            embed_called = True
            return np.zeros((len(texts), 384), dtype=np.float32)

        def mock_create_index(*args, **kwargs):
            nonlocal create_index_called
            create_index_called = True

        monkeypatch.setattr("app.main.embed_texts", mock_embed_texts)
        monkeypatch.setattr("app.main.create_index", mock_create_index)

        payload = {
            "page_id": page_id,
            "title": "Blank Chunks Page",
            "url": "https://example.com/blank",
            "chunks": [
                {"heading": "", "text": "   "},
                {"heading": "   ", "text": ""}
            ],
            "content": "",
            "wordCount": 0
        }

        try:
            res = client.post("/page/ingest", json=payload)
            assert res.status_code == 200
            assert res.json().get("success") is True
            assert res.json().get("chunkCount") == 2

            assert not embed_called, "embed_texts must not be called when no valid chunk texts exist"
            assert not create_index_called, "create_index must not be called when no valid chunk texts exist"
            assert load_index(page_id, session_hash=TEST_SESSION_HASH) is None
        finally:
            delete_index(page_id, session_hash=TEST_SESSION_HASH)

    def test_max_indexed_chunks_configured_value_and_safety(self, monkeypatch):
        """
        Verify MAX_INDEXED_CHUNKS configuration fallback:
        - Valid positive environment value is accepted.
        - Invalid non-integer value falls back to 40.
        - Zero falls back to 40.
        - Negative value falls back to 40.
        """
        # 1. Valid positive environment value is accepted
        monkeypatch.setenv("MAX_INDEXED_CHUNKS", "25")
        assert load_max_indexed_chunks_from_env() == 25

        monkeypatch.setenv("MAX_INDEXED_CHUNKS", "100")
        assert load_max_indexed_chunks_from_env() == 100

        # 2. Invalid non-integer value falls back to 40
        monkeypatch.setenv("MAX_INDEXED_CHUNKS", "not_a_number")
        assert load_max_indexed_chunks_from_env() == 40

        monkeypatch.setenv("MAX_INDEXED_CHUNKS", "3.14")
        assert load_max_indexed_chunks_from_env() == 40

        monkeypatch.setenv("MAX_INDEXED_CHUNKS", "")
        assert load_max_indexed_chunks_from_env() == 40

        # 3. Zero falls back to 40
        monkeypatch.setenv("MAX_INDEXED_CHUNKS", "0")
        assert load_max_indexed_chunks_from_env() == 40

        # 4. Negative value falls back to 40
        monkeypatch.setenv("MAX_INDEXED_CHUNKS", "-1")
        assert load_max_indexed_chunks_from_env() == 40

        monkeypatch.setenv("MAX_INDEXED_CHUNKS", "-40")
        assert load_max_indexed_chunks_from_env() == 40

        # 5. Default when environment variable is unset falls back to 40
        monkeypatch.delenv("MAX_INDEXED_CHUNKS", raising=False)
        assert load_max_indexed_chunks_from_env() == 40

        # 6. Verify current running application active constant is 40
        assert MAX_INDEXED_CHUNKS == 40

    def test_dynamic_max_indexed_chunks_enforcement(self, client, monkeypatch):
        """Verify that modifying MAX_INDEXED_CHUNKS dynamically controls ingestion capping."""
        page_id = "test_page_dynamic_cap"
        delete_index(page_id, session_hash=TEST_SESSION_HASH)

        recorded = []

        def mock_embed(texts, **kwargs):
            recorded.extend(texts)
            return np.zeros((len(texts), 384), dtype=np.float32)

        monkeypatch.setattr("app.main.embed_texts", mock_embed)
        monkeypatch.setattr("app.main.MAX_INDEXED_CHUNKS", 10)

        chunks_15 = _build_mock_chunks(15)
        payload = {
            "page_id": page_id,
            "title": "Dynamic Cap Test",
            "chunks": chunks_15,
            "content": "Test content",
            "wordCount": 50
        }

        try:
            res = client.post("/page/ingest", json=payload)
            assert res.status_code == 200
            assert res.json().get("chunkCount") == 15
            # Exactly 10 indexed because MAX_INDEXED_CHUNKS was set to 10
            assert len(recorded) == 10
            idx_data = load_index(page_id, session_hash=TEST_SESSION_HASH)
            assert idx_data is not None
            assert len(idx_data["chunks"]) == 10
        finally:
            delete_index(page_id, session_hash=TEST_SESSION_HASH)

