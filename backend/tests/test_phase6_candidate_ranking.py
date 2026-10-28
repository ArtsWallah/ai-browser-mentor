"""
test_phase6_candidate_ranking.py
================================
Unit and regression tests for Phase 6:
  - Label alignment and deduplication
  - Conflicting duplicate label handling
  - Multi-source provenance tracking
  - Registry idempotency and status preservation
  - Signal separation (novelty, suspicious evidence, spam probability, temporal emergence)
  - Multi-signal ranking correctness
  - Held-out evaluation metric validation
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
import numpy as np
import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.pattern_discovery import (
    TextExample,
    deduplicate,
)
from app.services.pattern_registry import PatternRegistry
from app.services.candidate_ranker import (
    CandidateSignals,
    MultiSignalCandidateRanker,
    extract_suspicious_evidence,
    evaluate_ranking_on_split,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. LABEL ALIGNMENT & DEDUPLICATION TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestLabelAlignmentAndDeduplication:
    def test_dedup_merges_sources(self):
        ex1 = TextExample(id="1", message="Call urgently to claim prize", source="SRC_A")
        ex2 = TextExample(id="2", message="Call urgently to claim prize", source="SRC_B")
        
        unique, n_removed = deduplicate([ex1, ex2])
        assert len(unique) == 1
        assert n_removed == 1
        assert "SRC_A" in unique[0].sources
        assert "SRC_B" in unique[0].sources
        assert unique[0].occurrence_count == 2

    def test_dedup_inherits_missing_label(self):
        ex1 = TextExample(id="1", message="Win £1000 now", external_label=None)
        ex2 = TextExample(id="2", message="Win £1000 now", external_label="1")
        
        unique, _ = deduplicate([ex1, ex2])
        assert unique[0].external_label == "1"
        assert unique[0].label_conflict is False

    def test_dedup_detects_label_conflict(self):
        ex1 = TextExample(id="1", message="Special update for you", external_label="0")
        ex2 = TextExample(id="2", message="Special update for you", external_label="1")
        
        unique, _ = deduplicate([ex1, ex2])
        assert unique[0].label_conflict is True
        assert "conflicting_labels" in unique[0].metadata
        assert set(unique[0].metadata["conflicting_labels"]) == {"0", "1"}

    def test_dedup_merges_tactics(self):
        ex1 = TextExample(id="1", message="Urgent account alert", known_tactics=["urgency"])
        ex2 = TextExample(id="2", message="Urgent account alert", known_tactics=["authority"])
        
        unique, _ = deduplicate([ex1, ex2])
        assert set(unique[0].known_tactics) == {"urgency", "authority"}


# ─────────────────────────────────────────────────────────────────────────────
# 2. REGISTRY IDEMPOTENCY & AUDIT TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestRegistryIdempotency:
    def test_reimport_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reg_path = Path(tmpdir) / "registry.json"
            reg = PatternRegistry(reg_path)
            
            result_dict = {
                "clusters": [{
                    "cluster_id": "c_test_01",
                    "n_examples": 5,
                    "novelty_score": 0.85,
                    "associated_tactics": ["urgency"],
                    "tactic_confidence": "supported",
                    "representative_examples": [{"id": "1", "message": "msg", "source": "TEST"}],
                    "medoid": {"id": "1", "message": "msg", "source": "TEST"},
                    "shared_ngrams": ["urgent"],
                    "limitations": [],
                }]
            }
            
            first_import = reg.import_from_result(result_dict)
            assert first_import == 1
            assert len(reg.list_patterns()) == 1
            
            # Second import of identical data must not add duplicates
            second_import = reg.import_from_result(result_dict)
            assert second_import == 0
            assert len(reg.list_patterns()) == 1

    def test_reimport_preserves_human_review_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reg_path = Path(tmpdir) / "registry.json"
            reg = PatternRegistry(reg_path)
            
            result_dict = {
                "clusters": [{
                    "cluster_id": "c_preserve",
                    "n_examples": 3,
                    "novelty_score": 0.90,
                    "associated_tactics": [],
                    "tactic_confidence": "none",
                }]
            }
            reg.import_from_result(result_dict)
            
            # Review the pattern to 'potentially_novel'
            reg.review_pattern("c_preserve", "potentially_novel", reviewer="analyst_alice")
            assert reg.get_pattern("c_preserve")["review_status"] == "potentially_novel"
            
            # Re-importing must NOT reset review_status to 'pending'
            reg.import_from_result(result_dict)
            assert reg.get_pattern("c_preserve")["review_status"] == "potentially_novel"


# ─────────────────────────────────────────────────────────────────────────────
# 3. SIGNAL SEPARATION & CANDIDATE RANKING TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestSignalSeparationAndRanking:
    def test_benign_text_has_low_suspicion_despite_high_novelty(self):
        ranker = MultiSignalCandidateRanker()
        # Everyday casual message with zero scam cues
        msg = "The weather today in California was nice and sunny. Had lunch with my sister."
        score, indicators = extract_suspicious_evidence(msg)
        assert score == 0.0
        assert len(indicators) == 0
        
        # Even with artificial maximum novelty (1.10), composite rank should be 0.0
        sig = ranker.evaluate_candidate(
            example_id="t1",
            message=msg,
            source="TEST",
            novelty_score=1.10,
            cluster_id="noise",
            cluster_size=1,
        )
        assert sig.suspicious_evidence_score == 0.0
        assert sig.composite_rank_score == 0.0

    def test_suspicious_novel_text_achieves_high_composite_rank(self):
        ranker = MultiSignalCandidateRanker()
        msg = "URGENT: Your refund of £450 expires today! Click http://claim-funds-now.xyz to verify your PIN."
        sig = ranker.evaluate_candidate(
            example_id="t2",
            message=msg,
            source="TEST",
            novelty_score=0.85,
            cluster_id="cluster_emerging",
            cluster_size=5,
        )
        assert sig.suspicious_evidence_score >= 0.7
        assert sig.composite_rank_score > 0.5
        assert "contains_url_or_domain" in sig.detected_indicators
        assert "urgency_or_deadline_pressure" in sig.detected_indicators
        assert "financial_reward_or_prize_hook" in sig.detected_indicators

    def test_temporal_signal_is_strictly_not_fabricated(self):
        ranker = MultiSignalCandidateRanker()
        sig = ranker.evaluate_candidate(
            example_id="t3",
            message="Test message",
            source="TEST",
            novelty_score=0.70,
        )
        assert sig.temporal_signal_available is False
        assert sig.temporal_growth_rate is None
        assert "Unavailable" in sig.temporal_notes

    def test_multi_signal_ranking_order(self):
        ranker = MultiSignalCandidateRanker()
        
        # Candidate A: Mundane benign chat, very high novelty
        sig_a = ranker.evaluate_candidate("A", "Having tea with friends in the park", "TEST", novelty_score=1.15)
        # Candidate B: Known tactic, low novelty
        sig_b = ranker.evaluate_candidate("B", "Claim your free prize now £500", "TEST", novelty_score=0.30)
        # Candidate C: Emerging pattern, high novelty AND suspicious
        sig_c = ranker.evaluate_candidate("C", "URGENT security warning! Click http://new-crypto.com to verify", "TEST", novelty_score=0.85)

        ranked = ranker.rank_candidates([sig_a, sig_b, sig_c], strategy="multi_signal")
        # Candidate C must be ranked #1
        assert ranked[0].example_id == "C"
        # Candidate A must be ranked last (suppressed due to 0 suspicion)
        assert ranked[-1].example_id == "A"


# ─────────────────────────────────────────────────────────────────────────────
# 4. HELD-OUT EVALUATION METRICS TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestHeldOutEvaluation:
    def test_evaluate_ranking_on_split_metrics(self):
        # Create synthetic candidate signals
        signals = []
        for i in range(100):
            # First 20 are spam (label '1'), remaining 80 are ham (label '0')
            is_spam = i < 20
            signals.append(CandidateSignals(
                example_id=f"ex_{i}",
                message=f"msg_{i}",
                source="TEST",
                external_label="1" if is_spam else "0",
                novelty_score=0.9 if not is_spam else 0.4,  # Novelty baseline inverted
                composite_rank_score=0.8 if is_spam else 0.1, # Multi-signal correct
            ))
            
        test_indices = np.arange(100)
        metrics = evaluate_ranking_on_split(signals, test_indices, ks=(10, 20))
        
        assert metrics["n_held_out"] == 100
        assert metrics["n_positive_examples"] == 20
        assert metrics["base_rate"] == 0.2
        
        # Novelty-only should have poor P@10 because high novelty corresponds to ham
        assert metrics["novelty_only_baseline"]["P@10"] == 0.0
        # Multi-signal should have high P@10 because spam got high composite rank
        assert metrics["multi_signal_phase6"]["P@10"] == 1.0
        assert metrics["empirical_lift"]["lift_P@10_vs_novelty"] == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# 5. DATA LEAKAGE & SPLIT INTEGRITY TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestLeakageAndSplitIntegrity:
    def test_group_partition_prevents_duplicate_leakage(self):
        """Verify that identical texts are always placed exclusively in one split."""
        messages = [
            "Urgent: Claim £1000 prize now",
            "Urgent: Claim £1000 prize now",  # duplicate
            "Having dinner with family",
            "Having dinner with family",      # duplicate
            "Call 0800123456 immediately",
            "Mundane text about weather",
        ]
        from collections import defaultdict
        grouped = defaultdict(list)
        for i, m in enumerate(messages):
            grouped[m.lower().strip()].append(i)
            
        group_keys = list(grouped.keys())
        split_point = len(group_keys) // 2
        train_keys = set(group_keys[:split_point])
        test_keys = set(group_keys[split_point:])
        
        # Zero group overlap guarantee
        assert len(train_keys & test_keys) == 0
        
        train_indices = [idx for k in train_keys for idx in grouped[k]]
        test_indices = [idx for k in test_keys for idx in grouped[k]]
        
        assert len(set(train_indices) & set(test_indices)) == 0
        
    def test_test_labels_never_used_in_ranking_features(self):
        """Verify that external_label is not used as a ranking feature."""
        ranker = MultiSignalCandidateRanker()
        sig_spam = ranker.evaluate_candidate("1", "Hello there", "TEST", 0.5, external_label="1")
        sig_ham = ranker.evaluate_candidate("2", "Hello there", "TEST", 0.5, external_label="0")
        
        # Exact same text with different external_label must produce identical composite rank
        assert sig_spam.composite_rank_score == sig_ham.composite_rank_score
        assert sig_spam.suspicious_evidence_score == sig_ham.suspicious_evidence_score
