import json
from pathlib import Path

import pytest

from app.scamshield_service import (
    get_scamshield_status,
    is_scamshield_available,
    load_model,
    resolve_model_path,
)
from app.services.candidate_ranker import MultiSignalCandidateRanker
from app.services.model_integrity import (
    ModelIntegrityError,
    compute_sha256,
    load_trusted_manifest,
    update_integrity_manifest,
    verify_model_artifact,
)
from app.services.security_service import analyze_security_text
from fastapi.testclient import TestClient
from app.main import app

BACKEND_DIR = Path(__file__).resolve().parents[1]
MODELS_DIR = BACKEND_DIR / "data" / "models"
DEFAULT_MANIFEST = MODELS_DIR / "model_integrity_manifest.json"


def test_manifest_exists_and_has_valid_schema():
    """Verify that committed model integrity manifest exists and has valid schema."""
    assert DEFAULT_MANIFEST.is_file(), "model_integrity_manifest.json must exist in data/models/"
    manifest = load_trusted_manifest(DEFAULT_MANIFEST)
    assert manifest.get("$schema") == "scamshield_model_integrity_v1"
    assert manifest.get("hash_algorithm") == "sha256"
    assert "models" in manifest
    models = manifest["models"]
    assert "baseline_tfidf_logistic.pkl" in models
    assert "tfidf_multilabel_baseline.joblib" in models

    for name, entry in models.items():
        assert "sha256" in entry
        assert len(entry["sha256"]) == 64
        assert entry["sha256"] == entry["sha256"].lower()
        assert "size_bytes" in entry
        assert entry["size_bytes"] > 0


def test_real_model_artifacts_integrity_verified():
    """Both committed model artifacts pass SHA-256 integrity verification."""
    spam_model = MODELS_DIR / "baseline_tfidf_logistic.pkl"
    tactic_model = MODELS_DIR / "tfidf_multilabel_baseline.joblib"

    assert spam_model.is_file()
    assert tactic_model.is_file()

    assert verify_model_artifact(spam_model, manifest_path=DEFAULT_MANIFEST) is True
    assert verify_model_artifact(tactic_model, manifest_path=DEFAULT_MANIFEST) is True


def test_modified_or_corrupted_model_artifact_rejected(tmp_path):
    """Corrupted or modified model artifact fails integrity check with ModelIntegrityError."""
    fake_model = tmp_path / "baseline_tfidf_logistic.pkl"
    fake_model.write_bytes(b"tampered or corrupted binary model payload")

    with pytest.raises(ModelIntegrityError) as exc_info:
        verify_model_artifact(fake_model, manifest_path=DEFAULT_MANIFEST)
    assert "Integrity check failed" in str(exc_info.value)
    assert "baseline_tfidf_logistic.pkl" in str(exc_info.value)


def test_explicit_expected_hash_mismatch_rejected(tmp_path):
    """Providing an invalid explicit expected hash raises ModelIntegrityError."""
    fake_model = tmp_path / "custom_model.pkl"
    fake_model.write_bytes(b"some model weights")

    with pytest.raises(ModelIntegrityError) as exc_info:
        verify_model_artifact(
            fake_model,
            expected_sha256="0000000000000000000000000000000000000000000000000000000000000000",
        )
    assert "Integrity check failed" in str(exc_info.value)


def test_unregistered_model_artifact_fails_safely(tmp_path):
    """Model file not in the manifest and without explicit hash fails safely."""
    unregistered = tmp_path / "unregistered_model.joblib"
    unregistered.write_bytes(b"valid joblib content")

    with pytest.raises(ModelIntegrityError) as exc_info:
        verify_model_artifact(unregistered, manifest_path=DEFAULT_MANIFEST)
    assert "No trusted integrity record found" in str(exc_info.value)


def test_missing_manifest_fails_safely(tmp_path):
    """Missing manifest file raises ModelIntegrityError."""
    model_file = MODELS_DIR / "tfidf_multilabel_baseline.joblib"
    nonexistent_manifest = tmp_path / "nonexistent_manifest.json"

    with pytest.raises(ModelIntegrityError) as exc_info:
        verify_model_artifact(model_file, manifest_path=nonexistent_manifest)
    assert "manifest not found" in str(exc_info.value).lower()


def test_malformed_manifest_fails_safely(tmp_path):
    """Malformed JSON manifest raises ModelIntegrityError without crashing."""
    bad_manifest = tmp_path / "bad_manifest.json"
    bad_manifest.write_text("{invalid json: broken", encoding="utf-8")

    model_file = MODELS_DIR / "tfidf_multilabel_baseline.joblib"
    with pytest.raises(ModelIntegrityError) as exc_info:
        verify_model_artifact(model_file, manifest_path=bad_manifest)
    assert "manifest is malformed" in str(exc_info.value).lower()


def test_manifest_missing_models_key_fails_safely(tmp_path):
    """Manifest JSON missing 'models' key raises ModelIntegrityError."""
    bad_manifest = tmp_path / "schema_missing.json"
    bad_manifest.write_text(json.dumps({"version": 1}), encoding="utf-8")

    model_file = MODELS_DIR / "tfidf_multilabel_baseline.joblib"
    with pytest.raises(ModelIntegrityError) as exc_info:
        verify_model_artifact(model_file, manifest_path=bad_manifest)
    assert "missing 'models' dictionary" in str(exc_info.value).lower()


def test_scamshield_service_load_model_succeeds_with_verified_artifact():
    """Normal model loading via scamshield_service succeeds and returns verified model."""
    load_model.cache_clear()
    model = load_model()
    assert isinstance(model, dict)
    assert model.get("model_type") == "per_tactic_binary_v1"
    assert "models" in model


def test_scamshield_service_load_model_rejects_corrupted_model(tmp_path, monkeypatch):
    """scamshield_service.load_model() blocks execution when corrupted model is configured."""
    corrupted_file = tmp_path / "tfidf_multilabel_baseline.joblib"
    corrupted_file.write_bytes(b"corrupted model content")

    load_model.cache_clear()
    monkeypatch.setenv("SCAMSHIELD_MODEL_PATH", str(corrupted_file))

    with pytest.raises(RuntimeError) as exc_info:
        load_model()
    assert "Integrity check failed" in str(exc_info.value) or "integrity" in str(exc_info.value).lower()
    load_model.cache_clear()


def test_candidate_ranker_falls_back_safely_when_model_corrupted(tmp_path):
    """MultiSignalCandidateRanker gracefully degrades to heuristic scoring if model checksum fails."""
    corrupted_spam = tmp_path / "baseline_tfidf_logistic.pkl"
    corrupted_spam.write_bytes(b"corrupted spam weights")

    corrupted_tactic = tmp_path / "tfidf_multilabel_baseline.joblib"
    corrupted_tactic.write_bytes(b"corrupted tactic weights")

    ranker = MultiSignalCandidateRanker(
        spam_model_path=corrupted_spam,
        tactic_model_path=corrupted_tactic,
    )
    # Both models should be None due to integrity rejection
    assert ranker.spam_model is None
    assert ranker.tactic_model is None

    # Scoring continues to function reliably via heuristic signals
    signals = ranker.evaluate_candidate(
        example_id="test_ex",
        message="URGENT: Claim your £5000 prize jackpot now!",
        source="TEST",
        novelty_score=0.75,
    )
    assert signals.example_id == "test_ex"
    assert signals.suspicious_evidence_score > 0
    assert signals.composite_rank_score > 0


def test_update_integrity_manifest_utility(tmp_path):
    """update_integrity_manifest utility regenerates a valid manifest from model files."""
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "test_model_a.pkl").write_bytes(b"model data a")
    (models_dir / "test_model_b.joblib").write_bytes(b"model data b")

    output_manifest = tmp_path / "new_manifest.json"
    manifest = update_integrity_manifest(models_dir=models_dir, output_path=output_manifest)

    assert output_manifest.is_file()
    assert manifest["$schema"] == "scamshield_model_integrity_v1"
    assert "test_model_a.pkl" in manifest["models"]
    assert "test_model_b.joblib" in manifest["models"]
    assert manifest["models"]["test_model_a.pkl"]["sha256"] == compute_sha256(models_dir / "test_model_a.pkl")


def test_dataset_attribution_notice_exists_and_accurate():
    """Verify that dataset attribution notice exists and satisfies all licensing requirements."""
    attribution_file = BACKEND_DIR / "data" / "scamshield" / "processed" / "ATTRIBUTION.md"
    assert attribution_file.is_file(), "ATTRIBUTION.md must be present in processed dataset directory"

    content = attribution_file.read_text(encoding="utf-8")

    # Author verification
    assert "Tiago A. Almeida" in content
    assert "José María Gómez Hidalgo" in content

    # Source & academic citations
    assert "UCI Machine Learning Repository" in content
    assert "DocEng" in content
    assert "ICMLA" in content

    # Licensing terms
    assert "Creative Commons Attribution 4.0 International" in content or "CC BY 4.0" in content

    # Independent licensing boundary distinction
    assert "Do not assume that every derived dataset, model artifact, or annotation file has the same license" in content


def test_readme_references_dataset_attribution():
    """Verify README documents the attribution and links to ATTRIBUTION.md."""
    readme_file = BACKEND_DIR.parent / "README.md"
    assert readme_file.is_file()
    content = readme_file.read_text(encoding="utf-8")

    assert "Tiago A. Almeida" in content
    assert "José María Gómez Hidalgo" in content
    assert "ATTRIBUTION.md" in content
    assert "CC BY 4.0" in content


def test_scamshield_readiness_valid_registered_artifact():
    """Readiness probe returns True and ready status when valid artifact is configured."""
    assert is_scamshield_available() is True
    available, msg = get_scamshield_status()
    assert available is True
    assert "Ready" in msg


def test_scamshield_readiness_missing_artifact(tmp_path, monkeypatch):
    """Readiness probe returns False when artifact file does not exist."""
    missing_file = tmp_path / "nonexistent.joblib"
    monkeypatch.setenv("SCAMSHIELD_MODEL_PATH", str(missing_file))

    assert is_scamshield_available() is False
    available, msg = get_scamshield_status()
    assert available is False
    assert "not found" in msg.lower() or "missing" in msg.lower()
    # Path should not leak in status message
    assert str(missing_file) not in msg


def test_scamshield_readiness_integrity_verification_failure(tmp_path, monkeypatch):
    """Readiness probe returns False when artifact fails SHA-256 integrity verification."""
    corrupted_file = tmp_path / "tfidf_multilabel_baseline.joblib"
    corrupted_file.write_bytes(b"tampered content that fails sha256")
    monkeypatch.setenv("SCAMSHIELD_MODEL_PATH", str(corrupted_file))

    assert is_scamshield_available() is False
    available, msg = get_scamshield_status()
    assert available is False
    assert "integrity" in msg.lower() or "checksum" in msg.lower()
    # Path should not leak in status message
    assert str(corrupted_file) not in msg


def test_health_and_models_endpoints_reflect_readiness(tmp_path, monkeypatch):
    """GET /health and GET /models/status report unavailable when model is corrupted."""
    client = TestClient(app)

    # 1. Normal state: healthy and configured
    health_ok = client.get("/health")
    assert health_ok.status_code == 200
    assert health_ok.json()["scamshield_configured"] is True

    models_ok = client.get("/models")
    assert models_ok.status_code == 200
    scamshield_model = next(m for m in models_ok.json()["models"] if m["id"] == "local-scamshield-classifier")
    assert scamshield_model["is_available"] is True
    assert scamshield_model["is_configured"] is True

    # 2. Corrupted state: reports unavailable
    corrupted_file = tmp_path / "tfidf_multilabel_baseline.joblib"
    corrupted_file.write_bytes(b"corrupted binary payload")
    monkeypatch.setenv("SCAMSHIELD_MODEL_PATH", str(corrupted_file))

    health_bad = client.get("/health")
    assert health_bad.status_code == 200
    assert health_bad.json()["scamshield_configured"] is False

    models_bad = client.get("/models/status")
    assert models_bad.status_code == 200
    scamshield_bad = next(m for m in models_bad.json()["models"] if m["id"] == "local-scamshield-classifier")
    assert scamshield_bad["is_available"] is False
    assert scamshield_bad["is_configured"] is False
    assert "integrity" in scamshield_bad["status_message"].lower() or "checksum" in scamshield_bad["status_message"].lower()
    # Must not leak filesystem paths
    assert str(corrupted_file) not in scamshield_bad["status_message"]


def test_heuristic_fallback_operates_when_model_unavailable(tmp_path, monkeypatch):
    """analyze_security_text gracefully falls back to heuristic checks without errors when model is corrupt."""
    corrupted_file = tmp_path / "tfidf_multilabel_baseline.joblib"
    corrupted_file.write_bytes(b"corrupted payload")
    monkeypatch.setenv("SCAMSHIELD_MODEL_PATH", str(corrupted_file))

    res = analyze_security_text("URGENT: Your account has been suspended! Enter password immediately to verify.")
    assert res["success"] is True
    assert res["risk_score"] > 0
    assert "reasons" in res
    assert res["scamshield"]["available"] is False
    assert "fallback" in res["scamshield"]["disclaimer"].lower() or "unavailable" in res["scamshield"]["disclaimer"].lower()


def test_readiness_probe_does_not_deserialize_model():
    """is_scamshield_available() and get_scamshield_status() do NOT trigger joblib.load()."""
    load_model.cache_clear()
    assert load_model.cache_info().currsize == 0

    # Probe availability
    available = is_scamshield_available()
    assert available is True
    _, msg = get_scamshield_status()
    assert "Ready" in msg

    # Cache should still be empty! Probing must not deserialize the model
    assert load_model.cache_info().currsize == 0


def test_heuristic_fallback_operates_when_scamshield_service_import_fails(monkeypatch):
    """security_service operates in fallback mode if scamshield_service raises ImportError."""
    import importlib
    import sys
    import app.services.security_service as sec

    # Simulate missing scamshield_service / ImportError
    monkeypatch.setitem(sys.modules, "app.scamshield_service", None)
    reloaded_sec = importlib.reload(sec)

    try:
        assert reloaded_sec.is_scamshield_available() is False
        res = reloaded_sec.analyze_security_text("URGENT: action required immediately. Enter your password.")
        assert res["success"] is True
        assert res["risk_score"] > 0
        assert res["scamshield"]["available"] is False
        assert "fallback" in res["scamshield"]["disclaimer"].lower() or "unavailable" in res["scamshield"]["disclaimer"].lower()
    finally:
        # Restore original module state
        monkeypatch.undo()
        importlib.reload(sec)
