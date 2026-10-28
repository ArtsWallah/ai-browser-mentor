"""
candidate_ranker.py
===================
ScamShield AI – Phase 6: Multi-Signal Candidate Ranking

Ranks discovered clusters and candidate texts for human review by fusing
distinct, orthogonal signals:
  1. Structural Novelty Signal (distance from known tactic prototypes)
  2. Suspicious-Tactic Evidence Signal (linguistic & structural solicitation markers)
  3. Supervised Spam/Scam Classification Signal (model probability if available)
  4. Cluster Density / Grouping Signal (noise point vs recurring pattern)
  5. Temporal Growth Signal (strictly documented as unavailable when timestamps missing)

GUARANTEES
----------
- Novelty, suspicious evidence, spam probability, and temporal emergence are kept
  strictly separate.
- No fabricated fraud probabilities.
- No assumption that SMS spam equals confirmed social-engineering scams.
- Explicit temporal status: never claims temporal emergence without actual timestamps.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

# ─────────────────────────────────────────────────────────────────────────────
# SUSPICIOUS PATTERN REGEXES (GROUNDED IN SOCIAL ENGINEERING INDICATORS)
# ─────────────────────────────────────────────────────────────────────────────

_URL_RE = re.compile(
    r"(?i)\b(?:https?://|www\d{0,3}[.]|[a-z0-9.\-]+[.](?:com|net|org|co|uk|xyz|info|biz|tk|ml|ga|cf|gq|club|top|vip|app|link|click|buzz|rest|live|online|site)/)\S*",
)
_PHONE_SHORTCODE_RE = re.compile(
    r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,5}\b|\b\d{4,6}\b",
)
_FINANCIAL_LURE_RE = re.compile(
    r"(?i)\b(?:prize|winner|won|congratulations|reward|gift|voucher|cash|free|bonus|claim|selected|awarded|refund|jackpot|guaranteed|credit|payout)\b|[£$€]\s*\d+",
)
_URGENCY_IMPERATIVE_RE = re.compile(
    r"(?i)\b(?:urgent|urgently|immediately|act now|today only|expires?|expiring|final notice|last chance|valid until|deadline|asap|within \d+ (?:hours?|days?|mins?))\b",
)
_SECURITY_CREDENTIAL_RE = re.compile(
    r"(?i)\b(?:suspended|suspension|locked|blocked|compromised|unauthorized|security alert|verify|verification|validate|pin|password|otp|security code|passcode|authenticate)\b",
)
_CALL_TO_ACTION_RE = re.compile(
    r"(?i)\b(?:call|txt|text|dial|reply|click|visit|contact|opt out|stop to)\b",
)


@dataclass
class CandidateSignals:
    """Distinct, un-conflated signals for an individual candidate message or cluster medoid."""
    example_id: str
    message: str
    source: str
    external_label: str | None = None
    
    # 1. Structural Novelty Signal
    novelty_score: float = 0.0
    nearest_tactic: str | None = None
    nearest_tactic_similarity: float = 0.0
    
    # 2. Suspicious Evidence Signal
    suspicious_evidence_score: float = 0.0
    detected_indicators: list[str] = field(default_factory=list)
    
    # 3. Supervised Classification Signal
    spam_probability: float | None = None
    tactic_model_max_score: float | None = None
    
    # 4. Cluster / Density Signal
    cluster_id: str | None = None
    cluster_size: int = 1
    is_noise: bool = True
    cluster_density_score: float = 0.0
    
    # 5. Temporal Growth Signal
    temporal_signal_available: bool = False
    temporal_growth_rate: float | None = None
    temporal_notes: str = "Unavailable: reference dataset does not contain timestamps."
    
    # Composite Rank & Explanation
    composite_rank_score: float = 0.0
    ranking_rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "example_id": self.example_id,
            "message": self.message,
            "source": self.source,
            "external_label": self.external_label,
            "novelty_score": round(self.novelty_score, 4),
            "nearest_tactic": self.nearest_tactic,
            "nearest_tactic_similarity": round(self.nearest_tactic_similarity, 4),
            "suspicious_evidence_score": round(self.suspicious_evidence_score, 4),
            "detected_indicators": self.detected_indicators,
            "spam_probability": round(self.spam_probability, 4) if self.spam_probability is not None else None,
            "tactic_model_max_score": round(self.tactic_model_max_score, 4) if self.tactic_model_max_score is not None else None,
            "cluster_id": self.cluster_id,
            "cluster_size": self.cluster_size,
            "is_noise": self.is_noise,
            "cluster_density_score": round(self.cluster_density_score, 4),
            "temporal_signal_available": self.temporal_signal_available,
            "temporal_growth_rate": self.temporal_growth_rate,
            "temporal_notes": self.temporal_notes,
            "composite_rank_score": round(self.composite_rank_score, 4),
            "ranking_rationale": self.ranking_rationale,
        }


def extract_suspicious_evidence(text: str) -> tuple[float, list[str]]:
    """
    Extract grounded social-engineering indicators and calculate suspiciousness score.
    Returns (score in [0, 1], list_of_matched_indicators).
    """
    if not text or not text.strip():
        return 0.0, []

    indicators: list[str] = []
    points = 0.0

    if _URL_RE.search(text):
        indicators.append("contains_url_or_domain")
        points += 0.35

    if _PHONE_SHORTCODE_RE.search(text):
        indicators.append("contains_phone_or_shortcode")
        points += 0.20

    if _FINANCIAL_LURE_RE.search(text):
        indicators.append("financial_reward_or_prize_hook")
        points += 0.35

    if _URGENCY_IMPERATIVE_RE.search(text):
        indicators.append("urgency_or_deadline_pressure")
        points += 0.30

    if _SECURITY_CREDENTIAL_RE.search(text):
        indicators.append("security_suspension_or_credential_cue")
        points += 0.35

    if _CALL_TO_ACTION_RE.search(text):
        indicators.append("call_to_action_imperative")
        points += 0.15

    # Normalize to [0.0, 1.0]
    score = min(1.0, points)
    return score, indicators


def _resolve_model_artifact(
    model_path: str | Path | None,
    env_var: str,
    default_relative: str,
) -> Path | None:
    """
    Resolve model path portably:
    1. Explicit path if provided.
    2. Environment variable if configured.
    3. Default path relative to backend root or current working directory.
    Returns resolved Path if file exists, else None.
    """
    raw = model_path or os.getenv(env_var)
    backend_dir = Path(__file__).resolve().parents[2]

    if raw:
        candidate = Path(raw).expanduser()
        if candidate.is_file():
            return candidate
        cand_backend = (backend_dir / candidate).resolve()
        if cand_backend.is_file():
            return cand_backend
        cand_cwd = (Path.cwd() / candidate).resolve()
        if cand_cwd.is_file():
            return cand_cwd
        return None

    # Check default relative path
    cand_default = (backend_dir / default_relative).resolve()
    if cand_default.is_file():
        return cand_default
    cand_cwd_default = (Path.cwd() / default_relative).resolve()
    if cand_cwd_default.is_file():
        return cand_cwd_default

    return None


class MultiSignalCandidateRanker:
    """
    Evaluates and ranks candidate emerging patterns by combining structural novelty,
    suspicious evidence, supervised classification, and cluster density.
    """

    def __init__(
        self,
        spam_model_path: str | Path | None = None,
        tactic_model_path: str | Path | None = None,
    ) -> None:
        self.spam_model = None
        self.tactic_model = None
        self._load_models(spam_model_path, tactic_model_path)

    def _load_models(
        self,
        spam_model_path: str | Path | None,
        tactic_model_path: str | Path | None,
    ) -> None:
        # Load spam classifier
        resolved_spam = _resolve_model_artifact(
            spam_model_path,
            env_var="SCAMSHIELD_SPAM_MODEL_PATH",
            default_relative="data/models/baseline_tfidf_logistic.pkl",
        )
        if resolved_spam:
            try:
                import joblib
                self.spam_model = joblib.load(resolved_spam)
            except Exception:
                self.spam_model = None
        else:
            self.spam_model = None

        # Load multi-tactic baseline classifier
        tactic_env = os.getenv("SCAMSHIELD_TACTIC_MODEL_PATH") or os.getenv("SCAMSHIELD_MODEL_PATH")
        resolved_tactic = _resolve_model_artifact(
            tactic_model_path or tactic_env,
            env_var="SCAMSHIELD_MODEL_PATH",
            default_relative="data/models/tfidf_multilabel_baseline.joblib",
        )
        if resolved_tactic:
            try:
                import joblib
                self.tactic_model = joblib.load(resolved_tactic)
            except Exception:
                self.tactic_model = None
        else:
            self.tactic_model = None

    def evaluate_candidate(
        self,
        example_id: str,
        message: str,
        source: str,
        novelty_score: float,
        nearest_tactic: str | None = None,
        nearest_tactic_similarity: float = 0.0,
        cluster_id: str | None = None,
        cluster_size: int = 1,
        external_label: str | None = None,
    ) -> CandidateSignals:
        """Evaluate all distinct signals for an individual message or cluster representative."""
        # 1. Suspicious evidence signal
        susp_score, indicators = extract_suspicious_evidence(message)

        # 2. Supervised spam probability signal
        spam_prob: float | None = None
        if self.spam_model is not None:
            try:
                probs = self.spam_model.predict_proba([message])[0]
                spam_prob = float(probs[1]) if len(probs) > 1 else float(probs[0])
            except Exception:
                spam_prob = None

        # 3. Multi-tactic model activation
        tactic_max: float | None = None
        if self.tactic_model is not None and isinstance(self.tactic_model, dict):
            try:
                models = self.tactic_model.get("models", {})
                scores = []
                for _, clf in models.items():
                    if hasattr(clf, "decision_function"):
                        scores.append(float(clf.decision_function([message])[0]))
                    elif hasattr(clf, "predict_proba"):
                        scores.append(float(clf.predict_proba([message])[0][1]))
                if scores:
                    tactic_max = float(max(scores))
            except Exception:
                tactic_max = None

        # 4. Cluster density signal
        is_noise = (cluster_id is None) or (cluster_id == "noise") or (cluster_size <= 1)
        if is_noise:
            cluster_density = 0.1
        elif cluster_size < 3:
            cluster_density = 0.3
        elif cluster_size < 5:
            cluster_density = 0.6
        else:
            cluster_density = 0.9

        # 5. Composite Ranking Formulation
        # Effective suspicion combines model probability and heuristic indicators
        if spam_prob is not None:
            raw_suspicion = max(spam_prob, susp_score)
        else:
            raw_suspicion = susp_score

        # Suppress logistic regression background prior (< 0.12) when no indicators present
        if raw_suspicion < 0.12 and susp_score == 0.0:
            effective_suspicion = 0.0
        else:
            effective_suspicion = raw_suspicion

        # Gated Multi-Signal Rank:
        # A candidate must exhibit suspicion > 0 to be an emerging scam candidate.
        # If effective_suspicion == 0 (e.g. mundane everyday chat), composite rank is 0.
        # If effective_suspicion > 0, score scales with both suspicion and novelty.
        composite_score = effective_suspicion * novelty_score * (0.7 + 0.3 * cluster_density)

        rationale_parts = []
        if effective_suspicion < 0.1:
            rationale_parts.append("Low suspicion: text lacks solicitation/manipulation markers.")
        else:
            rationale_parts.append(f"Suspicious signals detected: {', '.join(indicators) if indicators else 'model score'}.")
        
        if novelty_score > 0.65:
            rationale_parts.append(f"High structural novelty ({novelty_score:.3f}) relative to known tactics.")
        else:
            rationale_parts.append(f"Moderate/low novelty ({novelty_score:.3f}); close to '{nearest_tactic}'.")

        if not is_noise:
            rationale_parts.append(f"Coherent cluster with {cluster_size} examples.")
        else:
            rationale_parts.append("Isolated noise point.")

        return CandidateSignals(
            example_id=example_id,
            message=message,
            source=source,
            external_label=external_label,
            novelty_score=novelty_score,
            nearest_tactic=nearest_tactic,
            nearest_tactic_similarity=nearest_tactic_similarity,
            suspicious_evidence_score=susp_score,
            detected_indicators=indicators,
            spam_probability=spam_prob,
            tactic_model_max_score=tactic_max,
            cluster_id=cluster_id,
            cluster_size=cluster_size,
            is_noise=is_noise,
            cluster_density_score=cluster_density,
            temporal_signal_available=False,
            temporal_growth_rate=None,
            temporal_notes="Unavailable: reference dataset does not contain timestamps.",
            composite_rank_score=composite_score,
            ranking_rationale=" ".join(rationale_parts),
        )

    def rank_candidates(
        self,
        candidates: list[CandidateSignals],
        strategy: str = "multi_signal",
    ) -> list[CandidateSignals]:
        """
        Rank candidate signals according to the specified strategy:
        - 'multi_signal': composite_rank_score descending (Phase 6)
        - 'novelty_only': novelty_score descending (Phase 5 baseline)
        - 'suspicion_only': suspicious_evidence_score descending
        """
        if strategy == "novelty_only":
            return sorted(candidates, key=lambda c: c.novelty_score, reverse=True)
        elif strategy == "suspicion_only":
            return sorted(candidates, key=lambda c: c.suspicious_evidence_score, reverse=True)
        else:
            return sorted(candidates, key=lambda c: c.composite_rank_score, reverse=True)


# ─────────────────────────────────────────────────────────────────────────────
# EVALUATION ROUTINES ON HELD-OUT DATA
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_ranking_on_split(
    candidate_signals: list[CandidateSignals],
    test_indices: np.ndarray,
    ks: tuple[int, ...] = (10, 20, 50, 100),
) -> dict[str, Any]:
    """
    Evaluates Phase 6 multi-signal ranking vs Phase 5 novelty-only baseline on held-out test indices.
    
    Parameters
    ----------
    candidate_signals : list of pre-computed CandidateSignals for the entire dataset.
    test_indices : array of integer indices representing the held-out test split.
    ks : thresholds for Precision@K and Recall@K.
    
    Returns
    -------
    dict containing P@K, Recall@K, Base Rate, and Lift comparison.
    """
    test_candidates = [candidate_signals[i] for i in test_indices]
    
    # Ground truth labels (1 = spam/scam, 0 = ham)
    labels = np.array([
        1 if (c.external_label == "1" or c.external_label == "spam") else 0
        for c in test_candidates
    ])
    
    n_total = len(labels)
    n_pos = int(labels.sum())
    base_rate = float(n_pos / n_total) if n_total > 0 else 0.0

    # 1. Novelty-only baseline ranking (Phase 5)
    novelty_scores = np.array([c.novelty_score for c in test_candidates])
    rank_novelty = np.argsort(-novelty_scores)
    
    # 2. Multi-signal ranking (Phase 6)
    multi_scores = np.array([c.composite_rank_score for c in test_candidates])
    rank_multi = np.argsort(-multi_scores)

    results: dict[str, Any] = {
        "n_held_out": n_total,
        "n_positive_examples": n_pos,
        "base_rate": round(base_rate, 4),
        "novelty_only_baseline": {},
        "multi_signal_phase6": {},
        "empirical_lift": {},
    }

    for k in ks:
        k_eff = min(k, n_total)
        
        # Novelty baseline
        top_k_nov = labels[rank_novelty[:k_eff]]
        p_nov = float(top_k_nov.mean()) if k_eff > 0 else 0.0
        rec_nov = float(top_k_nov.sum() / n_pos) if n_pos > 0 else 0.0
        
        # Multi-signal
        top_k_multi = labels[rank_multi[:k_eff]]
        p_multi = float(top_k_multi.mean()) if k_eff > 0 else 0.0
        rec_multi = float(top_k_multi.sum() / n_pos) if n_pos > 0 else 0.0
        
        results["novelty_only_baseline"][f"P@{k}"] = round(p_nov, 4)
        results["novelty_only_baseline"][f"Recall@{k}"] = round(rec_nov, 4)
        
        results["multi_signal_phase6"][f"P@{k}"] = round(p_multi, 4)
        results["multi_signal_phase6"][f"Recall@{k}"] = round(rec_multi, 4)
        
        results["empirical_lift"][f"lift_P@{k}_vs_novelty"] = round(p_multi - p_nov, 4)
        results["empirical_lift"][f"lift_P@{k}_vs_random"] = round(p_multi - base_rate, 4)

    return results
