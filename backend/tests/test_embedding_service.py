"""
Unit and integration tests for backend/app/services/embedding_service.py.

Verifies:
1. FastEmbed TextEmbedding is initialized with threads=1.
2. Embedding calls use batch_size=16.
3. Empty input returns expected shape (0, 384) and float32 dtype.
4. Output dimensions (384) and dtype (float32) remain unchanged.
5. Existing model singleton behavior is preserved across calls.
6. Thread-safe initialization under concurrent access with try/finally restoration.
7. Internal TypeError from model.embed() propagates directly without retry.
8. Memory diagnostic checkpoints are invoked.
"""

import threading
import numpy as np
import pytest

from app.services import embedding_service


class TestEmbeddingService:
    def test_model_singleton_and_threads_config(self):
        """Verify FastEmbed model is configured with threads=1 and maintains singleton."""
        model1 = embedding_service.get_model()
        model2 = embedding_service.get_model()

        assert model1 is model2, "get_model() must return the same singleton instance"
        assert hasattr(model1, "threads"), "Model must expose threads attribute"
        assert model1.threads == 1, "Model must be initialized with threads=1"

    def test_thread_safe_singleton_initialization(self):
        """Verify thread-safe initialization under concurrent thread access."""
        old_model = embedding_service._model
        threads = []
        try:
            embedding_service._model = None

            created_models = []
            exceptions = []
            barrier = threading.Barrier(5)

            def worker():
                try:
                    barrier.wait(timeout=5)
                    m = embedding_service.get_model()
                    created_models.append(m)
                except Exception as exc:
                    exceptions.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

            assert not any(t.is_alive() for t in threads)

            # Assert no thread failed
            assert not exceptions, f"Worker thread raised exception: {exceptions}"
            assert len(created_models) == 5, f"Expected 5 models, got {len(created_models)}"

            first = created_models[0]
            assert all(m is first for m in created_models), "All threads must obtain the exact same model instance"
            assert getattr(first, "threads", None) == 1
        finally:
            for t in threads:
                if t.is_alive():
                    t.join(timeout=2)
            embedding_service._model = old_model

    def test_embed_texts_empty_input(self):
        """Empty input must safely return a float32 array with shape (0, 384)."""
        res = embedding_service.embed_texts([])
        assert isinstance(res, np.ndarray)
        assert res.shape == (0, 384)
        assert res.dtype == np.float32

    def test_embed_texts_batch_size_parameter(self, monkeypatch):
        """Verify embed_texts passes batch_size=16 by default to model.embed()."""
        recorded_kwargs = {}

        class DummyModel:
            threads = 1
            def embed(self, documents, **kwargs):
                recorded_kwargs.update(kwargs)
                for _ in documents:
                    yield np.zeros(384, dtype=np.float32)

        monkeypatch.setattr(embedding_service, "get_model", lambda: DummyModel())

        texts = ["Sample chunk 1", "Sample chunk 2"]
        res = embedding_service.embed_texts(texts)

        assert recorded_kwargs.get("batch_size") == 16, "model.embed must receive batch_size=16"
        assert res.shape == (2, 384)
        assert res.dtype == np.float32

    def test_internal_type_error_propagates_without_retry(self, monkeypatch):
        """Verify an internal TypeError from model.embed() propagates directly and does not retry."""
        call_count = 0

        class FaultyModel:
            threads = 1
            def embed(self, documents, **kwargs):
                nonlocal call_count
                call_count += 1
                raise TypeError("Simulated internal TypeError inside model.embed")

        monkeypatch.setattr(embedding_service, "get_model", lambda: FaultyModel())

        with pytest.raises(TypeError, match="Simulated internal TypeError"):
            embedding_service.embed_texts(["sample text"])

        assert call_count == 1, f"Expected exactly 1 call to embed(), but was called {call_count} times"

        # Also verify embed_text
        call_count = 0
        with pytest.raises(TypeError, match="Simulated internal TypeError"):
            embedding_service.embed_text("sample text")

        assert call_count == 1, f"Expected exactly 1 call to embed(), but was called {call_count} times"

    def test_embed_text_single_string(self):
        """Verify embed_text returns 1D array of shape (384,) with float32."""
        vec = embedding_service.embed_text("Security analysis of browser extensions")
        assert isinstance(vec, np.ndarray)
        assert vec.shape == (384,)
        assert vec.dtype == np.float32
        assert not np.isnan(vec).any()

    def test_embed_texts_multiple_strings(self):
        """Verify embed_texts returns 2D array of shape (N, 384) with float32."""
        texts = [
            "Introduction to AI Browser Mentor.",
            "Phishing detection heuristics and multi-tactic analysis.",
            "Research workspace comparison across active browser tabs."
        ]
        res = embedding_service.embed_texts(texts)
        assert isinstance(res, np.ndarray)
        assert res.shape == (3, 384)
        assert res.dtype == np.float32
        assert not np.isnan(res).any()

    def test_memory_checkpoints_logged(self, monkeypatch):
        """Verify diagnostic checkpoints are called during embedding generation."""
        checkpoints = []

        def mock_log(cp):
            checkpoints.append(cp)

        monkeypatch.setattr(embedding_service, "log_memory_checkpoint", mock_log)

        embedding_service.embed_texts(["Test chunk"])
        assert "embedding_generation_begin" in checkpoints
        assert "embedding_generation_complete" in checkpoints
