"""
test_portability_phase1b.py
===========================
Phase 1B Portability & Path Audit Tests:
  - Verifies absence of hardcoded machine-specific Windows paths across repo.
  - Verifies portable path resolution for ScamShield models and datasets.
  - Verifies independence of current working directory.
  - Verifies predictable, graceful handling of missing optional files.
  - Verifies preserved candidate-ranking behavior.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

REPO_ROOT = BACKEND_DIR.parent

from app.scamshield_service import resolve_model_path
from app.services.candidate_ranker import (
    MultiSignalCandidateRanker,
    _resolve_model_artifact,
)
from app.services.audit_error_analyzer import run_error_analysis
from scamshield_discovery_pipeline import _resolve_scamshield_data_dir


class TestNoHardcodedMachinePaths:
    """Audit executable source, config, and documentation for machine-specific paths."""

    TARGET_MACHINE_FRAGMENT = "C:\\Users\\DELL"

    def test_no_hardcoded_machine_paths_in_repo(self):
        """Ensure no hardcoded C:\\Users\\DELL paths exist in project source, configs, or docs."""
        scanned_extensions = {".py", ".json", ".js", ".html", ".css", ".md", ".env", ".example", ".yml", ".yaml"}
        ignored_dir_names = {".git", ".venv", "venv", "__pycache__", "vector_store", ".gemini", "node_modules"}

        violating_files: list[str] = []

        for root, dirs, files in os.walk(REPO_ROOT):
            dirs[:] = [d for d in dirs if d not in ignored_dir_names]
            for file_name in files:
                file_path = Path(root) / file_name
                # Check target file types or .env files
                if file_path.suffix.lower() in scanned_extensions or file_name.startswith(".env"):
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                        if self.TARGET_MACHINE_FRAGMENT.lower() in content.lower():
                            violating_files.append(str(file_path.relative_to(REPO_ROOT)))
                    except Exception:
                        pass

        assert not violating_files, f"Hardcoded machine paths found in: {violating_files}"


class TestPathResolutionPortability:
    """Test resolution of models and datasets regardless of cwd."""

    def test_candidate_ranker_model_artifact_resolver_with_missing_file(self):
        """Resolver should return None for non-existent files rather than crashing."""
        res = _resolve_model_artifact(
            model_path="nonexistent_model_12345.joblib",
            env_var="NONEXISTENT_VAR_XYZ",
            default_relative="data/models/nonexistent.joblib",
        )
        assert res is None

    def test_candidate_ranker_model_artifact_resolver_with_env_var(self, monkeypatch):
        """Resolver should respect environment variable override."""
        with tempfile.NamedTemporaryFile(suffix=".joblib", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            monkeypatch.setenv("TEST_SCAMSHIELD_CUSTOM_MODEL", str(tmp_path))
            resolved = _resolve_model_artifact(
                model_path=None,
                env_var="TEST_SCAMSHIELD_CUSTOM_MODEL",
                default_relative="data/models/fallback.joblib",
            )
            assert resolved is not None
            assert resolved.resolve() == tmp_path.resolve()
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def test_scamshield_service_resolve_model_path_cwd_independence(self):
        """resolve_model_path should locate data/models/tfidf_multilabel_baseline.joblib from backend."""
        model_path = resolve_model_path("./data/models/tfidf_multilabel_baseline.joblib")
        assert model_path.is_file()

    def test_discovery_pipeline_data_dir_resolution(self):
        """_resolve_scamshield_data_dir should return a valid directory path."""
        data_dir = _resolve_scamshield_data_dir()
        assert isinstance(data_dir, Path)
        # Verify it points to backend/data or backend/data/scamshield
        assert "data" in str(data_dir).lower()


class TestGracefulDegradationOnMissingFiles:
    """Verify safe fallback behavior when optional files are missing."""

    def test_candidate_ranker_handles_missing_models_gracefully(self):
        """Ranker should initialize with None models when files do not exist."""
        ranker = MultiSignalCandidateRanker(
            spam_model_path="nonexistent/spam.pkl",
            tactic_model_path="nonexistent/tactic.joblib",
        )
        assert ranker.spam_model is None
        assert ranker.tactic_model is None

        # Evaluating a candidate should not throw an exception
        sig = ranker.evaluate_candidate(
            example_id="deg_001",
            message="URGENT: Click http://claim-award.xyz to verify your account credentials immediately",
            source="TEST",
            novelty_score=0.88,
        )
        assert sig.spam_probability is None
        assert sig.suspicious_evidence_score > 0.0
        assert sig.composite_rank_score > 0.0
        assert "contains_url_or_domain" in sig.detected_indicators

    def test_audit_error_analyzer_raises_filenotfound_on_missing_dataset(self):
        """run_error_analysis should raise FileNotFoundError when dataset does not exist."""
        with pytest.raises(FileNotFoundError) as exc_info:
            run_error_analysis(
                dataset_path="data/nonexistent_dataset_abc.csv",
                training_data_path="data/nonexistent_trn_abc.csv",
            )
        assert "Dataset file not found at" in str(exc_info.value)
