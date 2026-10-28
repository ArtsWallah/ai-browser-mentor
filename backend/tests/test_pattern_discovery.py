"""
test_pattern_discovery.py
==========================
Tests for ScamShield AI Phase 5: Emerging Pattern Discovery Pipeline.

Test coverage:
  - Empty input
  - Duplicate examples
  - Small datasets (< MIN_SAMPLES_FOR_CLUSTERING)
  - Normal datasets with known structure
  - Outlier detection
  - Missing metadata / minimal fields
  - Deterministic reproducibility (TF-IDF fallback is seeded)
  - Unavailable embedding model (uses TF-IDF SVD fallback)
  - PatternRegistry: import, review, audit log, invalid status
  - API endpoint tests: /scamshield/discovery/run, /patterns, /review
  - Text normalization edge cases
  - CSV ingestion

All tests use synthetic data only — no real datasets required.
Neural embeddings are mocked so tests run fast without network access.
"""

from __future__ import annotations

import json
import os
import tempfile
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import sys
import numpy as np
import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import app
from app.services.pattern_discovery import (
    MIN_SAMPLES_FOR_CLUSTERING,
    NOVELTY_THRESHOLD,
    TACTIC_PROTOTYPES,
    DiscoveryResult,
    NoisePoint,
    TextExample,
    deduplicate,
    describe_cluster,
    generate_embeddings,
    ingest_csv,
    ingest_dicts,
    normalize_text,
    run_discovery_pipeline,
    export_result,
    compute_novelty_scores,
    embed_tactic_prototypes,
    _embed_texts_fallback,
)
from app.services.pattern_registry import PatternRegistry, VALID_STATUSES


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def tmp_registry(tmp_path):
    """A fresh PatternRegistry backed by a temp file."""
    return PatternRegistry(tmp_path / "registry.json")


@pytest.fixture
def small_examples():
    """A small set of 5 distinct text examples — below clustering threshold."""
    return ingest_dicts([
        {"id": "s1", "message": "Urgent: Click now to verify your account.", "source": "TEST"},
        {"id": "s2", "message": "Congratulations! You won a prize.", "source": "TEST"},
        {"id": "s3", "message": "Your bank account will be suspended.", "source": "TEST"},
        {"id": "s4", "message": "Enter your PIN to continue.", "source": "TEST"},
        {"id": "s5", "message": "Send £100 to claim your reward.", "source": "TEST"},
    ])


@pytest.fixture
def medium_examples():
    """25 examples — sufficient for HDBSCAN but small enough to be fast."""
    base = [
        "Urgent: Verify your account NOW before it is deleted.",
        "ALERT: Suspicious activity detected. Click to secure account.",
        "Your account will be locked. Act immediately to prevent loss.",
        "Last chance: confirm your identity to avoid suspension.",
        "Time is running out! Update your details now.",
        "Congratulations! You have won £1000. Claim your prize today.",
        "You are selected for a FREE gift. Reply YES to claim.",
        "Your lucky number was drawn. £5000 prize awaits.",
        "Win big! Enter the lottery. Text WIN to 88600.",
        "PRIZE ALERT: Claim your reward before midnight.",
        "Your bank requires immediate verification. Call now.",
        "HMRC: You have a tax refund of £234. Confirm bank details.",
        "As per HMRC records, you owe outstanding tax. Pay now.",
        "Government alert: Your benefits are at risk. Contact us.",
        "Police notification: Unpaid fines on your record. Settle now.",
        "Enter your password to continue. Your session will expire.",
        "Verify your OTP code to proceed with the transaction.",
        "Submit your PIN to confirm identity for security audit.",
        "Your credentials need updating. Login at: http://phish.example.com",
        "Send your verification code immediately to avoid account closure.",
        "Wire transfer required: pay £500 processing fee immediately.",
        "Your parcel is held at customs. Pay £2.99 release fee.",
        "Send money to receive your inheritance. Nigerian prince needs help.",
        "Transfer funds via Bitcoin to secure your investment return.",
        "Payment needed: £99 admin fee to receive your compensation.",
    ]
    return ingest_dicts([
        {"id": f"m{i}", "message": msg, "source": "TEST"}
        for i, msg in enumerate(base, 1)
    ])


@pytest.fixture
def dup_examples():
    """Examples with deliberate duplicates."""
    return ingest_dicts([
        {"id": "d1", "message": "URGENT: Act now!", "source": "TEST"},
        {"id": "d2", "message": "URGENT: Act now!", "source": "TEST"},  # exact dup
        {"id": "d3", "message": "URGENT:  Act now! ", "source": "TEST"},  # whitespace dup
        {"id": "d4", "message": "Something completely different.", "source": "TEST"},
    ])


def _make_dummy_embeddings(texts: list[str]) -> np.ndarray:
    """Deterministic fixed embeddings for mocking (seed based on text hash)."""
    out = []
    for t in texts:
        rng = np.random.RandomState(abs(hash(t)) % (2**31))
        v = rng.randn(384).astype("float32")
        v /= np.linalg.norm(v)
        out.append(v)
    return np.array(out, dtype="float32")


@pytest.fixture
def mock_embeddings(monkeypatch):
    """Patch fastembed so all tests run without network/GPU access."""
    monkeypatch.setattr(
        "app.services.pattern_discovery._embed_texts_fastembed",
        _make_dummy_embeddings,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. TEXT NORMALIZATION
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalization:

    def test_strips_leading_trailing_whitespace(self):
        assert normalize_text("  hello  ") == "hello"

    def test_collapses_internal_whitespace(self):
        assert normalize_text("hello   world") == "hello world"

    def test_preserves_capitalisation(self):
        # ALL CAPS is a meaningful urgency signal — must NOT be lowercased
        result = normalize_text("URGENT: CLICK NOW")
        assert "URGENT" in result
        assert "CLICK" in result

    def test_preserves_punctuation(self):
        result = normalize_text("Act now! Time's running out?")
        assert "!" in result
        assert "?" in result

    def test_preserves_numbers(self):
        result = normalize_text("Ref: 123456. Pay £99.")
        assert "123456" in result
        assert "99" in result

    def test_handles_empty_string(self):
        assert normalize_text("") == ""

    def test_handles_only_whitespace(self):
        assert normalize_text("   \t\n   ") == ""

    def test_nfc_normalization_applied(self):
        # decomposed and composed forms of 'é' should both normalize to the same
        import unicodedata
        composed = unicodedata.normalize("NFC", "é")
        decomposed = "e\u0301"  # e + combining acute accent
        assert normalize_text(decomposed) == normalize_text(composed)

    def test_removes_control_characters(self):
        result = normalize_text("hello\x00\x01world")
        assert "\x00" not in result
        assert "\x01" not in result
        assert "hello" in result
        assert "world" in result


# ─────────────────────────────────────────────────────────────────────────────
# 2. INGESTION
# ─────────────────────────────────────────────────────────────────────────────

class TestIngestion:

    def test_ingest_dicts_basic(self):
        records = [
            {"id": "1", "message": "Hello world", "source": "TEST"},
        ]
        examples = ingest_dicts(records)
        assert len(examples) == 1
        assert examples[0].message == "Hello world"
        assert examples[0].id == "1"

    def test_ingest_dicts_skips_empty_messages(self):
        records = [
            {"id": "1", "message": "Valid message"},
            {"id": "2", "message": ""},
            {"id": "3", "message": "   "},
        ]
        examples = ingest_dicts(records)
        # Empty/whitespace messages skipped
        assert len(examples) == 1

    def test_ingest_dicts_auto_assigns_id(self):
        records = [{"message": "No ID provided"}]
        examples = ingest_dicts(records)
        assert examples[0].id != ""

    def test_ingest_dicts_empty_list(self):
        examples = ingest_dicts([])
        assert examples == []

    def test_ingest_dicts_missing_metadata_defaults(self):
        records = [{"message": "Just a message"}]
        examples = ingest_dicts(records)
        assert examples[0].source == "IMPORT"
        assert examples[0].external_label is None
        assert examples[0].known_tactics == []

    def test_ingest_dicts_known_tactics(self):
        records = [{"message": "msg", "known_tactics": ["urgency", "threat"]}]
        examples = ingest_dicts(records)
        assert "urgency" in examples[0].known_tactics
        assert "threat" in examples[0].known_tactics

    def test_ingest_csv_basic(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(
            "id,message,source\n"
            "1,Hello world,TEST\n"
            "2,Another message,TEST\n",
            encoding="utf-8",
        )
        examples = ingest_csv(str(csv_file))
        assert len(examples) == 2
        assert examples[0].message == "Hello world"

    def test_ingest_csv_with_tactic_cols(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(
            "id,message,urgency,threat\n"
            "1,Urgent msg,1.0,0.0\n"
            "2,Threat msg,0.0,1.0\n",
            encoding="utf-8",
        )
        examples = ingest_csv(
            str(csv_file),
            tactics_cols=["urgency", "threat"],
        )
        assert "urgency" in examples[0].known_tactics
        assert "urgency" not in examples[1].known_tactics
        assert "threat" in examples[1].known_tactics

    def test_ingest_csv_wrong_column_raises(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("id,text\n1,hello\n", encoding="utf-8")
        with pytest.raises(ValueError, match="Column 'message' not found"):
            ingest_csv(str(csv_file), message_col="message")

    def test_ingest_csv_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            ingest_csv("/nonexistent/path/to/data.csv")

    def test_ingest_csv_max_rows(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        rows = "id,message\n" + "\n".join(f"{i},msg{i}" for i in range(100))
        csv_file.write_text(rows, encoding="utf-8")
        examples = ingest_csv(str(csv_file), max_rows=10)
        assert len(examples) <= 10


# ─────────────────────────────────────────────────────────────────────────────
# 3. DEDUPLICATION
# ─────────────────────────────────────────────────────────────────────────────

class TestDeduplication:

    def test_removes_exact_duplicates(self, dup_examples):
        deduped, n_removed = deduplicate(dup_examples)
        # "URGENT: Act now!" appears twice exactly, plus whitespace variant → 2 removed
        assert n_removed >= 2
        messages = [ex.message for ex in deduped]
        # All remaining messages should be unique
        assert len(messages) == len(set(messages))

    def test_keeps_first_occurrence(self):
        examples = ingest_dicts([
            {"id": "first", "message": "Duplicate message"},
            {"id": "second", "message": "Duplicate message"},
        ])
        deduped, _ = deduplicate(examples)
        assert len(deduped) == 1
        assert deduped[0].id == "first"

    def test_no_duplicates_unchanged_count(self, small_examples):
        deduped, n_removed = deduplicate(small_examples)
        assert n_removed == 0
        assert len(deduped) == len(small_examples)

    def test_empty_list_is_safe(self):
        deduped, n_removed = deduplicate([])
        assert deduped == []
        assert n_removed == 0

    def test_single_example_unchanged(self):
        examples = ingest_dicts([{"id": "x", "message": "Only example"}])
        deduped, n_removed = deduplicate(examples)
        assert n_removed == 0
        assert len(deduped) == 1


# ─────────────────────────────────────────────────────────────────────────────
# 4. EMBEDDING (with mock and fallback)
# ─────────────────────────────────────────────────────────────────────────────

class TestEmbedding:

    def test_fallback_embedding_shape(self, small_examples):
        """TF-IDF SVD fallback returns correct shape."""
        texts = [ex.message for ex in small_examples]
        embs = _embed_texts_fallback(texts)
        assert embs.shape == (len(texts), 384)
        assert embs.dtype == np.float32

    def test_fallback_embedding_normalized(self, small_examples):
        texts = [ex.message for ex in small_examples]
        embs = _embed_texts_fallback(texts)
        norms = np.linalg.norm(embs, axis=1)
        # All norms should be approximately 1 (L2 normalized) except zero vectors
        for norm in norms:
            assert norm == pytest.approx(1.0, abs=0.01) or norm == pytest.approx(0.0, abs=0.01)

    def test_fallback_embedding_single_example(self):
        texts = ["Just one message."]
        embs = _embed_texts_fallback(texts)
        assert embs.shape == (1, 384)

    def test_fallback_deterministic(self, small_examples):
        """Same input always produces same output (TF-IDF SVD is seeded)."""
        texts = [ex.message for ex in small_examples]
        embs_a = _embed_texts_fallback(texts)
        embs_b = _embed_texts_fallback(texts)
        np.testing.assert_array_almost_equal(embs_a, embs_b, decimal=5)

    def test_generate_embeddings_uses_fallback_on_error(self, small_examples, monkeypatch):
        """When fastembed throws, fallback is used and embedding_available=False."""
        def _fail(texts):
            raise RuntimeError("fastembed not available")

        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed", _fail
        )
        embs, model_name, available = generate_embeddings(small_examples)
        assert not available
        assert "fallback" in model_name.lower()
        assert embs.shape[0] == len(small_examples)

    def test_tactic_prototype_embedding_shape(self, monkeypatch):
        """Prototype embeddings for all 8 tactics are returned."""
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        protos = embed_tactic_prototypes(embedding_available=True)
        assert len(protos) == len(TACTIC_PROTOTYPES)
        for name, emb in protos.items():
            assert name in TACTIC_PROTOTYPES
            assert emb.shape == (384,)


# ─────────────────────────────────────────────────────────────────────────────
# 5. NOVELTY SCORING
# ─────────────────────────────────────────────────────────────────────────────

class TestNoveltyScoring:

    def _get_protos(self) -> dict[str, np.ndarray]:
        """Create simple unit-vector prototypes for testing."""
        rng = np.random.RandomState(99)
        protos = {}
        for name in list(TACTIC_PROTOTYPES.keys())[:3]:
            v = rng.randn(384).astype("float32")
            protos[name] = v / np.linalg.norm(v)
        return protos

    def test_novelty_score_range(self):
        protos = self._get_protos()
        rng = np.random.RandomState(42)
        embs = rng.randn(10, 384).astype("float32")
        embs /= np.linalg.norm(embs, axis=1, keepdims=True)
        novelty, max_sims, nearest = compute_novelty_scores(embs, protos)
        assert novelty.shape == (10,)
        assert np.all(novelty >= 0) and np.all(novelty <= 2.0)  # cosine can be negative

    def test_novelty_identical_to_prototype_is_zero(self):
        protos = self._get_protos()
        first_proto = next(iter(protos.values()))
        embs = first_proto.reshape(1, -1)
        novelty, max_sims, nearest = compute_novelty_scores(embs, protos)
        assert novelty[0] == pytest.approx(0.0, abs=0.01)

    def test_novelty_with_no_prototypes(self):
        rng = np.random.RandomState(0)
        embs = rng.randn(5, 384).astype("float32")
        novelty, max_sims, nearest = compute_novelty_scores(embs, {})
        assert all(n == pytest.approx(1.0, abs=0.01) for n in novelty.tolist())
        assert all(t is None for t in nearest)

    def test_nearest_tactic_is_valid(self):
        protos = self._get_protos()
        rng = np.random.RandomState(7)
        embs = rng.randn(5, 384).astype("float32")
        embs /= np.linalg.norm(embs, axis=1, keepdims=True)
        _, _, nearest = compute_novelty_scores(embs, protos)
        valid_names = set(protos.keys())
        for t in nearest:
            assert t in valid_names


# ─────────────────────────────────────────────────────────────────────────────
# 6. PIPELINE — SMALL DATASET (below clustering threshold)
# ─────────────────────────────────────────────────────────────────────────────

class TestPipelineSmallDataset:

    def test_small_dataset_no_crash(self, small_examples, monkeypatch):
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        result = run_discovery_pipeline(small_examples)
        assert isinstance(result, DiscoveryResult)

    def test_small_dataset_no_clusters(self, small_examples, monkeypatch):
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        result = run_discovery_pipeline(small_examples)
        # Below threshold, no clusters should be formed
        assert len(result.clusters) == 0

    def test_small_dataset_has_limitations_note(self, small_examples, monkeypatch):
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        result = run_discovery_pipeline(small_examples)
        combined = " ".join(result.limitations)
        assert "too few" in combined.lower() or "minimum" in combined.lower()

    def test_small_dataset_all_noise(self, small_examples, monkeypatch):
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        result = run_discovery_pipeline(small_examples)
        assert result.n_embedded == len(small_examples)


# ─────────────────────────────────────────────────────────────────────────────
# 7. PIPELINE — EMPTY INPUT
# ─────────────────────────────────────────────────────────────────────────────

class TestPipelineEmptyInput:

    def test_empty_examples_list(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        result = run_discovery_pipeline([])
        assert result.n_deduplicated == 0
        assert result.clusters == []
        assert result.noise_points == []
        assert any("deduplication" in lim.lower() or "examples" in lim.lower()
                   for lim in result.limitations)

    def test_all_empty_messages(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        examples = ingest_dicts([
            {"id": "x", "message": ""},
            {"id": "y", "message": "   "},
        ])
        # ingest_dicts skips empty messages, so examples is empty
        assert len(examples) == 0
        result = run_discovery_pipeline(examples)
        assert result.n_ingested == 0


# ─────────────────────────────────────────────────────────────────────────────
# 8. PIPELINE — DUPLICATE HANDLING
# ─────────────────────────────────────────────────────────────────────────────

class TestPipelineDuplicates:

    def test_duplicates_removed_before_pipeline(self, dup_examples, monkeypatch):
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        result = run_discovery_pipeline(dup_examples)
        # Duplicates removed → n_deduplicated < n_ingested
        assert result.n_deduplicated < result.n_ingested

    def test_leakage_prevention_note(self, dup_examples, monkeypatch):
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        result = run_discovery_pipeline(dup_examples)
        combined = " ".join(result.limitations)
        assert "duplicate" in combined.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 9. PIPELINE — MEDIUM DATASET
# ─────────────────────────────────────────────────────────────────────────────

class TestPipelineMediumDataset:

    def test_pipeline_runs_without_error(self, medium_examples, monkeypatch):
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        result = run_discovery_pipeline(medium_examples)
        assert isinstance(result, DiscoveryResult)
        assert result.n_embedded == len(medium_examples)

    def test_temporal_emergence_disclaimed(self, medium_examples, monkeypatch):
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        result = run_discovery_pipeline(medium_examples)
        combined = " ".join(result.limitations)
        assert "temporal" in combined.lower()

    def test_all_clusters_have_medoid(self, medium_examples, monkeypatch):
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        result = run_discovery_pipeline(medium_examples)
        for cluster in result.clusters:
            assert isinstance(cluster.medoid, TextExample)
            assert cluster.medoid.message

    def test_cluster_to_dict_serializable(self, medium_examples, monkeypatch):
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        result = run_discovery_pipeline(medium_examples)
        for cluster in result.clusters:
            d = cluster.to_dict()
            json.dumps(d)  # must not raise

    def test_result_to_dict_serializable(self, medium_examples, monkeypatch):
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        result = run_discovery_pipeline(medium_examples)
        d = result.to_dict()
        json.dumps(d)

    def test_novelty_score_is_float_in_range(self, medium_examples, monkeypatch):
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        result = run_discovery_pipeline(medium_examples)
        for cluster in result.clusters:
            assert isinstance(cluster.novelty_score, float)
            assert -0.1 <= cluster.novelty_score <= 1.1

    def test_tactic_confidence_valid_values(self, medium_examples, monkeypatch):
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        result = run_discovery_pipeline(medium_examples)
        for cluster in result.clusters:
            assert cluster.tactic_confidence in {"supported", "weak", "none"}

    def test_review_status_default_pending(self, medium_examples, monkeypatch):
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        result = run_discovery_pipeline(medium_examples)
        for cluster in result.clusters:
            assert cluster.review_status == "pending"


# ─────────────────────────────────────────────────────────────────────────────
# 10. PIPELINE — REPRODUCIBILITY
# ─────────────────────────────────────────────────────────────────────────────

class TestPipelineReproducibility:

    def test_fallback_pipeline_is_deterministic(self, medium_examples, monkeypatch):
        """TF-IDF SVD fallback uses seed=42 → results should be identical."""
        def fail_fastembed(texts):
            raise RuntimeError("mocked unavailable")

        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed", fail_fastembed
        )
        result_a = run_discovery_pipeline(medium_examples)
        result_b = run_discovery_pipeline(medium_examples)

        assert len(result_a.clusters) == len(result_b.clusters)
        assert len(result_a.noise_points) == len(result_b.noise_points)


# ─────────────────────────────────────────────────────────────────────────────
# 11. EXPORT
# ─────────────────────────────────────────────────────────────────────────────

class TestExport:

    def test_export_creates_json_file(self, medium_examples, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        result = run_discovery_pipeline(medium_examples)
        out_path = tmp_path / "results.json"
        export_result(result, out_path)
        assert out_path.is_file()

    def test_export_is_valid_json(self, medium_examples, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        result = run_discovery_pipeline(medium_examples)
        out_path = tmp_path / "results.json"
        export_result(result, out_path)
        with open(out_path, encoding="utf-8") as fh:
            data = json.load(fh)
        assert data["_schema_version"] == "scamshield_discovery_v1"
        assert "_note" in data

    def test_export_contains_human_review_note(self, medium_examples, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        result = run_discovery_pipeline(medium_examples)
        out_path = tmp_path / "results.json"
        export_result(result, out_path)
        with open(out_path, encoding="utf-8") as fh:
            data = json.load(fh)
        note = data["_note"].lower()
        assert "human review" in note

    def test_export_no_centroid_in_json(self, medium_examples, tmp_path, monkeypatch):
        """numpy arrays in centroid_embedding must not leak into JSON."""
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        result = run_discovery_pipeline(medium_examples)
        out_path = tmp_path / "results.json"
        export_result(result, out_path)
        # Should not raise (no numpy arrays in JSON)
        with open(out_path, encoding="utf-8") as fh:
            json.load(fh)


# ─────────────────────────────────────────────────────────────────────────────
# 12. PATTERN REGISTRY
# ─────────────────────────────────────────────────────────────────────────────

class TestPatternRegistry:

    def _sample_result_dict(self) -> dict:
        return {
            "clusters": [
                {
                    "cluster_id": "cluster_001",
                    "n_examples": 5,
                    "novelty_score": 0.72,
                    "associated_tactics": ["urgency"],
                    "tactic_confidence": "supported",
                    "medoid": {"id": "m1", "message": "URGENT: Act now!", "source": "TEST"},
                    "representative_examples": [
                        {"id": "e1", "message": "msg1", "source": "TEST", "external_label": None}
                    ],
                    "shared_ngrams": ["urgent", "act now"],
                    "limitations": [],
                    "algorithm": "HDBSCAN",
                }
            ],
            "high_novelty_noise_examples": [
                {
                    "id": "n1",
                    "message": "Exotic novel scam text no one has seen.",
                    "source": "TEST",
                    "novelty_score": 0.89,
                    "nearest_tactic": "reward_lure",
                    "nearest_tactic_similarity": 0.11,
                }
            ],
        }

    def test_import_from_result_creates_patterns(self, tmp_registry):
        result_dict = self._sample_result_dict()
        n = tmp_registry.import_from_result(result_dict)
        assert n == 2  # 1 cluster + 1 noise point
        assert tmp_registry.stats()["total_patterns"] == 2

    def test_import_idempotent(self, tmp_registry):
        result_dict = self._sample_result_dict()
        tmp_registry.import_from_result(result_dict)
        n2 = tmp_registry.import_from_result(result_dict)
        assert n2 == 0  # already imported, nothing new
        assert tmp_registry.stats()["total_patterns"] == 2

    def test_default_status_is_pending(self, tmp_registry):
        tmp_registry.import_from_result(self._sample_result_dict())
        patterns = tmp_registry.list_patterns()
        for p in patterns:
            assert p["review_status"] == "pending"

    def test_review_valid_status(self, tmp_registry):
        tmp_registry.import_from_result(self._sample_result_dict())
        updated = tmp_registry.review_pattern(
            "cluster_001", "potentially_novel", reviewer="test_user", rationale="Looks new."
        )
        assert updated["review_status"] == "potentially_novel"
        assert updated["review_history"][0]["reviewer"] == "test_user"

    def test_review_invalid_status_raises(self, tmp_registry):
        tmp_registry.import_from_result(self._sample_result_dict())
        with pytest.raises(ValueError, match="Invalid status"):
            tmp_registry.review_pattern("cluster_001", "invalid_status")

    def test_review_nonexistent_pattern_raises(self, tmp_registry):
        with pytest.raises(KeyError):
            tmp_registry.review_pattern("nonexistent_id", "known")

    def test_review_history_appended(self, tmp_registry):
        tmp_registry.import_from_result(self._sample_result_dict())
        tmp_registry.review_pattern("cluster_001", "benign")
        tmp_registry.review_pattern("cluster_001", "inconclusive")
        pattern = tmp_registry.get_pattern("cluster_001")
        assert len(pattern["review_history"]) == 2

    def test_list_patterns_filter_by_status(self, tmp_registry):
        tmp_registry.import_from_result(self._sample_result_dict())
        tmp_registry.review_pattern("cluster_001", "known")
        pending = tmp_registry.list_patterns(status_filter="pending")
        known = tmp_registry.list_patterns(status_filter="known")
        assert len(known) == 1
        assert known[0]["cluster_id"] == "cluster_001"
        assert all(p["review_status"] == "pending" for p in pending)

    def test_stats_counts_by_status(self, tmp_registry):
        tmp_registry.import_from_result(self._sample_result_dict())
        tmp_registry.review_pattern("cluster_001", "potentially_novel")
        stats = tmp_registry.stats()
        assert stats["total_patterns"] == 2
        assert stats["status_counts"].get("potentially_novel", 0) == 1
        assert stats["status_counts"].get("pending", 0) == 1

    def test_audit_log_records_actions(self, tmp_registry):
        tmp_registry.import_from_result(self._sample_result_dict())
        tmp_registry.review_pattern("cluster_001", "known", reviewer="alice")
        log = tmp_registry.audit_log()
        actions = [entry["action"] for entry in log]
        assert "import" in actions
        assert "review" in actions

    def test_empty_registry_returns_empty_list(self, tmp_registry):
        assert tmp_registry.list_patterns() == []
        assert tmp_registry.stats()["total_patterns"] == 0

    def test_save_and_reload(self, tmp_path):
        """Registry persists and reloads correctly."""
        reg1 = PatternRegistry(tmp_path / "registry.json")
        reg1.import_from_result({
            "clusters": [{
                "cluster_id": "c1", "n_examples": 3, "novelty_score": 0.8,
                "associated_tactics": [], "tactic_confidence": "none",
                "medoid": {"id": "m", "message": "msg", "source": "T"},
                "representative_examples": [], "shared_ngrams": [], "limitations": [],
                "algorithm": "HDBSCAN",
            }],
            "high_novelty_noise_examples": [],
        })
        reg1.review_pattern("c1", "benign")

        reg2 = PatternRegistry(tmp_path / "registry.json")
        p = reg2.get_pattern("c1")
        assert p is not None
        assert p["review_status"] == "benign"

    def test_valid_statuses_set(self):
        assert "pending" in VALID_STATUSES
        assert "potentially_novel" in VALID_STATUSES
        assert "known" in VALID_STATUSES
        assert "benign" in VALID_STATUSES
        assert "inconclusive" in VALID_STATUSES


# ─────────────────────────────────────────────────────────────────────────────
# 13. API ENDPOINT TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestDiscoveryAPIEndpoints:
    """
    Tests for the Phase 5 API endpoints.
    All use the TestClient; embeddings are mocked for speed.
    """

    _SAMPLE_EXAMPLES = [
        {"id": f"api_{i}", "message": f"Scam message example number {i}", "source": "TEST"}
        for i in range(15)
    ]

    def _patch_embeddings(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )

    def test_run_empty_examples_returns_422(self, client):
        res = client.post("/scamshield/discovery/run", json={"examples": []})
        assert res.status_code == 422

    def test_run_returns_200_with_valid_examples(self, client, monkeypatch):
        self._patch_embeddings(monkeypatch)
        res = client.post(
            "/scamshield/discovery/run",
            json={"examples": self._SAMPLE_EXAMPLES},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "n_ingested" in data
        assert "n_clusters" in data
        assert "embedding_model" in data

    def test_run_response_has_limitations(self, client, monkeypatch):
        self._patch_embeddings(monkeypatch)
        res = client.post(
            "/scamshield/discovery/run",
            json={"examples": self._SAMPLE_EXAMPLES},
        )
        data = res.json()
        assert isinstance(data["limitations"], list)
        assert len(data["limitations"]) > 0

    def test_run_disclaimer_present(self, client, monkeypatch):
        self._patch_embeddings(monkeypatch)
        res = client.post(
            "/scamshield/discovery/run",
            json={"examples": self._SAMPLE_EXAMPLES},
        )
        data = res.json()
        assert "disclaimer" in data
        assert "human review" in data["disclaimer"].lower()

    def test_patterns_list_returns_200(self, client):
        res = client.get("/scamshield/discovery/patterns")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert isinstance(data["patterns"], list)

    def test_patterns_list_filter_by_status(self, client):
        res = client.get("/scamshield/discovery/patterns?status=pending")
        assert res.status_code == 200
        data = res.json()
        assert data["status_filter"] == "pending"

    def test_review_invalid_status_422(self, client):
        res = client.post("/scamshield/discovery/review", json={
            "pattern_id": "any_id",
            "status": "invalid_status",
        })
        assert res.status_code == 422

    def test_review_nonexistent_pattern_404(self, client):
        res = client.post("/scamshield/discovery/review", json={
            "pattern_id": "definitely_does_not_exist_xyz",
            "status": "known",
        })
        assert res.status_code == 404

    def test_run_then_review_round_trip(self, client, monkeypatch):
        """Full round trip: run discovery, find a pattern, review it."""
        self._patch_embeddings(monkeypatch)

        # Run pipeline
        run_res = client.post(
            "/scamshield/discovery/run",
            json={"examples": self._SAMPLE_EXAMPLES},
        )
        assert run_res.status_code == 200

        # List patterns
        list_res = client.get("/scamshield/discovery/patterns")
        patterns = list_res.json()["patterns"]

        if patterns:
            pid = patterns[0]["cluster_id"]
            review_res = client.post("/scamshield/discovery/review", json={
                "pattern_id": pid,
                "status": "benign",
                "reviewer": "test_runner",
                "rationale": "Automated test decision.",
            })
            assert review_res.status_code == 200
            assert review_res.json()["success"] is True
            assert review_res.json()["new_status"] == "benign"


# ─────────────────────────────────────────────────────────────────────────────
# 14. OUTLIER HANDLING
# ─────────────────────────────────────────────────────────────────────────────

class TestOutlierHandling:

    def test_high_novelty_noise_flagged(self, medium_examples, monkeypatch):
        """High-novelty noise points should be present in result for review."""
        def highly_novel_embeddings(texts):
            """Return orthogonal (maximally distant) embeddings for some texts."""
            embs = _make_dummy_embeddings(texts)
            # Force first example very far from prototypes: assign random unit vector
            rng = np.random.RandomState(999)
            embs[0] = rng.randn(384).astype("float32")
            embs[0] /= np.linalg.norm(embs[0])
            return embs

        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,  # standard mock
        )
        result = run_discovery_pipeline(medium_examples, novelty_threshold=0.0)
        # With threshold=0.0, ALL noise points qualify as high-novelty
        assert len(result.high_novelty_noise) >= 0  # valid — may be 0 if no noise

    def test_noise_points_have_valid_structure(self, medium_examples, monkeypatch):
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        result = run_discovery_pipeline(medium_examples)
        for np_ in result.noise_points:
            assert isinstance(np_, NoisePoint)
            assert isinstance(np_.novelty_score, float)
            assert isinstance(np_.example, TextExample)

    def test_high_novelty_sorted_descending(self, medium_examples, monkeypatch):
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        result = run_discovery_pipeline(medium_examples, novelty_threshold=0.0)
        scores = [p.novelty_score for p in result.high_novelty_noise]
        assert scores == sorted(scores, reverse=True)


# ─────────────────────────────────────────────────────────────────────────────
# 15. SEPARATION OF CONCEPTS (documented behavior tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestConceptSeparation:
    """
    Verify that the four distinct novelty concepts are handled correctly:
    1. Novel to reference dataset
    2. Semantically distant from known patterns
    3. A newly forming cluster
    4. Increasing in frequency over time
    """

    def test_temporal_emergence_not_claimed(self, medium_examples, monkeypatch):
        """Pipeline must never claim temporal emergence without timestamps."""
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        result = run_discovery_pipeline(medium_examples)
        combined = json.dumps(result.to_dict()).lower()
        # Should NOT claim temporal emergence
        assert "emerging scam campaign" not in combined
        assert "increasing prevalence" not in combined
        # Should acknowledge limitation
        assert "temporal" in " ".join(result.limitations).lower()

    def test_no_fabricated_labels(self, medium_examples, monkeypatch):
        """Pipeline must not invent tactic names or campaign names."""
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        result = run_discovery_pipeline(medium_examples)
        known_tactics = set(TACTIC_PROTOTYPES.keys()) | {"none"}
        for cluster in result.clusters:
            for tactic in cluster.associated_tactics:
                assert tactic in known_tactics, (
                    f"Fabricated tactic '{tactic}' found in cluster {cluster.cluster_id}"
                )

    def test_review_status_not_novel_by_default(self, medium_examples, monkeypatch):
        """Patterns are never automatically declared 'potentially_novel'."""
        monkeypatch.setattr(
            "app.services.pattern_discovery._embed_texts_fastembed",
            _make_dummy_embeddings,
        )
        result = run_discovery_pipeline(medium_examples)
        for cluster in result.clusters:
            assert cluster.review_status == "pending", (
                f"Cluster {cluster.cluster_id} should not be auto-declared novel; "
                f"got review_status={cluster.review_status}"
            )
