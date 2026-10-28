"""
test_phase7_validation_audit.py
===============================
Unit and regression tests for Phase 7:
  - Evidence span fidelity (exact substring verification)
  - Feature ablation & attribution faithfulness
  - Tactic classifier availability and error handling
  - Error taxonomy categorization logic
  - External data separation guarantees (no leakage into training sets)
"""

import sys
import tempfile
from pathlib import Path
import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.scamshield_service import analyze_message, explain_tactic_prediction
from app.services.audit_error_analyzer import categorize_error, run_error_analysis


# ─────────────────────────────────────────────────────────────────────────────
# 1. EVIDENCE SPAN FIDELITY & ABLATION FAITHFULNESS
# ─────────────────────────────────────────────────────────────────────────────

class TestExplainabilityFidelity:
    def test_spans_are_exact_substrings(self):
        msg = "URGENT: Your account has been compromised. Verify your PIN at http://bank-secure.xyz immediately."
        res = analyze_message(msg)
        
        for finding in res["tactic_findings"]:
            for span in finding.get("evidence_spans", []):
                start = span["start"]
                end = span["end"]
                text = span["text"]
                # Mathematical guarantee: slice must match extracted text exactly
                assert msg[start:end] == text
                assert span["contribution"] > 0

    def test_feature_ablation_reduces_score(self):
        """Ablating a positive indicator term must reduce the tactic detection score."""
        msg = "You have won a free cash prize of £1000! Claim your reward now."
        res = analyze_message(msg)
        
        reward_finding = next((f for f in res["tactic_findings"] if f["tactic"] == "reward_lure"), None)
        assert reward_finding is not None
        assert reward_finding["detected"] is True
        
        orig_score = reward_finding["score"]
        spans = reward_finding["evidence_spans"]
        assert len(spans) > 0
        
        # Ablate top span from message
        top_span = spans[0]["text"]
        ablated_msg = msg.replace(top_span, "item")
        res_ablated = analyze_message(ablated_msg)
        
        ablated_finding = next((f for f in res_ablated["tactic_findings"] if f["tactic"] == "reward_lure"), None)
        assert ablated_finding is not None
        ablated_score = ablated_finding["score"]
        
        # Score must strictly decrease when positive feature is removed
        assert ablated_score < orig_score

    def test_unavailable_tactic_explanation(self):
        """When a tactic classifier is missing (like 'fear'), finding must report unavailable."""
        finding = explain_tactic_prediction(classifier=None, message="Test message", tactic="fear")
        assert finding["available"] is False
        assert finding["score"] is None
        assert finding["explanation_method"] == "unavailable"
        assert "unavailable" in finding["explanation"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# 2. ERROR TAXONOMY CATEGORIZATION TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestErrorTaxonomy:
    def test_categorize_commercial_promotion_false_positive(self):
        msg = "Big weekend sale! Up to 50% discount and special vouchers at our store."
        cat = categorize_error(msg, true_label=0, pred_label=1, score=0.65, indicators=["financial_reward_or_prize_hook"])
        assert cat == "COMMERCIAL_PROMOTION_VS_FRAUD"

    def test_categorize_subthreshold_urgency_false_positive(self):
        msg = "Please call me back immediately when you get home."
        cat = categorize_error(msg, true_label=0, pred_label=1, score=0.58, indicators=["urgency_or_deadline_pressure"])
        assert cat == "SUBTHRESHOLD_URGENCY"

    def test_categorize_informal_slang_error(self):
        msg = "wat r u doing tonite? c u soon"
        cat = categorize_error(msg, true_label=0, pred_label=1, score=0.55, indicators=[])
        assert cat == "INFORMAL_SLANG_OR_PHONETIC"

    def test_categorize_correct_prediction(self):
        msg = "Hello friend, how are you today?"
        cat = categorize_error(msg, true_label=0, pred_label=0, score=0.05, indicators=[])
        assert cat == "CORRECT"


# ─────────────────────────────────────────────────────────────────────────────
# 3. EXTERNAL DATA SEPARATION GUARANTEE
# ─────────────────────────────────────────────────────────────────────────────

class TestExternalDataSeparation:
    def test_clean_split_execution_and_schema(self):
        """Verify that run_error_analysis executes cleanly and produces structured artifacts."""
        import csv
        import os

        backend_dir = Path(__file__).resolve().parents[1]
        raw_data_dir = os.getenv("SCAMSHIELD_DATA_DIR")

        uci_path = None
        trn_path = None
        if raw_data_dir:
            cand_uci = Path(raw_data_dir).expanduser() / "processed" / "uci_sms_clean.csv"
            cand_trn = Path(raw_data_dir).expanduser() / "processed" / "final_training_data.csv"
            if cand_uci.is_file():
                uci_path = cand_uci
                trn_path = cand_trn

        if uci_path is None:
            cand_uci = backend_dir / "data" / "scamshield" / "processed" / "uci_sms_clean.csv"
            cand_trn = backend_dir / "data" / "scamshield" / "processed" / "final_training_data.csv"
            if cand_uci.is_file():
                uci_path = cand_uci
                trn_path = cand_trn

        with tempfile.TemporaryDirectory() as tmpdir:
            out_json = Path(tmpdir) / "error_audit.json"

            if uci_path is None or not uci_path.is_file():
                uci_path = Path(tmpdir) / "uci_sample.csv"
                trn_path = Path(tmpdir) / "trn_sample.csv"
                with open(uci_path, "w", encoding="utf-8", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(["id", "label", "message", "source"])
                    for idx in range(30):
                        writer.writerow([f"h_{idx}", "0", f"Hey friend how are you doing today sample message {idx}", "UCI_SMS"])
                    for idx in range(15):
                        writer.writerow([f"s_{idx}", "1", f"URGENT: Win £1000 cash prize claim now free entry {idx} call immediately", "UCI_SMS"])
                with open(trn_path, "w", encoding="utf-8", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(["id", "message"])
                    writer.writerow(["t_0", "Hey friend how are you doing today sample message 0"])

            res = run_error_analysis(uci_path, trn_path, output_path=out_json, test_ratio=0.20, random_seed=42)

            assert out_json.is_file()
            assert "performance_metrics" in res
            assert "error_taxonomy" in res
            assert res["performance_metrics"]["f1_score"] > 0.85
            assert res["metadata"]["leak_free_partition_guarantee"] == "0 duplicate groups cross partition"
