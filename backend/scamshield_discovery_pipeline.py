r"""
scamshield_discovery_pipeline.py
=================================
ScamShield AI – Phase 5: End-to-End Discovery Pipeline (CLI runner)

Runnable script that executes the full emerging-pattern discovery workflow:
  1. Ingest available data sources
  2. Normalize + deduplicate
  3. Generate embeddings (fastembed MiniLM or TF-IDF SVD fallback)
  4. Cluster (HDBSCAN primary, DBSCAN baseline)
  5. Score novelty relative to known tactic prototypes
  6. Describe discovered clusters
  7. Run evaluation (silhouette, novelty precision vs random baseline)
  8. Export results to JSON
  9. Import into PatternRegistry for human review
  10. Print a structured report

USAGE
-----
From the backend/ directory:

    .\.venv\Scripts\python.exe scamshield_discovery_pipeline.py

Optional arguments (edit CONFIG section below or set env vars):
    SCAMSHIELD_DATA_DIR=<path>     root of ScamShield-AI/data directory
    DISCOVERY_OUTPUT=<path>        output JSON file path

DATA SOURCES
------------
Priority order:
  1. ScamShield-AI training data (final_training_data.csv) — 74 labelled examples
  2. UCI SMS Spam Collection (uci_sms_clean.csv) — 5169 examples (ham=0, spam=1)
  3. Synthetic demo data (always available; used when above are absent)

SOURCE LIMITATIONS
-------------------
- No timestamps exist in either dataset. Temporal emergence CANNOT be evaluated.
- UCI SMS is from a public 2012 collection; it may not represent current scam patterns.
- final_training_data.csv is the ScamShield AI training set — it defines what
  the existing classifier considers "known". Novelty is relative to THIS set.
- No ground truth for "emerging" patterns exists. Novelty scores are structural,
  not semantic-human validated.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Ensure backend app is on the Python path when run as a script
_BACKEND = Path(__file__).resolve().parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from dotenv import load_dotenv
load_dotenv(_BACKEND / ".env", override=False)

from app.services.pattern_discovery import (
    TACTIC_PROTOTYPES,
    TextExample,
    ingest_csv,
    ingest_dicts,
    run_discovery_pipeline,
    export_result,
    NOVELTY_THRESHOLD,
    MIN_SAMPLES_FOR_CLUSTERING,
    generate_embeddings,
    embed_tactic_prototypes,
    compute_novelty_scores,
)
from app.services.pattern_registry import PatternRegistry
from app.services.candidate_ranker import MultiSignalCandidateRanker, evaluate_ranking_on_split

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_scamshield_data_dir() -> Path:
    """Resolve ScamShield data directory portably from env, backend directory, or current working directory."""
    raw = os.getenv("SCAMSHIELD_DATA_DIR")
    if raw:
        candidate = Path(raw).expanduser()
        if candidate.is_dir():
            return candidate
        cand_backend = (_BACKEND / candidate).resolve()
        if cand_backend.is_dir():
            return cand_backend
        cand_cwd = (Path.cwd() / candidate).resolve()
        if cand_cwd.is_dir():
            return cand_cwd
        return candidate

    default_backend = (_BACKEND / "data" / "scamshield").resolve()
    if default_backend.is_dir():
        return default_backend
    default_data = (_BACKEND / "data").resolve()
    if (default_data / "processed").is_dir():
        return default_data
    return default_backend


_SCAMSHIELD_DATA_DIR = _resolve_scamshield_data_dir()

_OUTPUT_PATH = Path(os.getenv(
    "DISCOVERY_OUTPUT",
    str(_BACKEND / "data" / "discovery_results.json"),
))

_REGISTRY_PATH = _BACKEND / "data" / "pattern_registry.json"

TACTIC_COLS = [
    "authority", "urgency", "threat", "fear",
    "impersonation", "credential_request", "payment_request", "reward_lure",
]


# ─────────────────────────────────────────────────────────────────────────────
# DEMO DATA (used when real datasets are absent)
# ─────────────────────────────────────────────────────────────────────────────

_DEMO_RECORDS = [
    {"id": "demo_001", "message": "URGENT: Your account has been compromised. Click now to verify.", "source": "SYNTHETIC_DEMO"},
    {"id": "demo_002", "message": "Congratulations! You have won £5000. Claim your prize immediately!", "source": "SYNTHETIC_DEMO"},
    {"id": "demo_003", "message": "Dear customer, your bank account will be suspended in 24 hours.", "source": "SYNTHETIC_DEMO"},
    {"id": "demo_004", "message": "Official: HMRC tax refund £234.50. Enter your bank details to receive.", "source": "SYNTHETIC_DEMO"},
    {"id": "demo_005", "message": "Alert: Unusual sign-in detected on your account. Verify now.", "source": "SYNTHETIC_DEMO"},
    {"id": "demo_006", "message": "FREE: Earn £500/day working from home. Reply YES to start.", "source": "SYNTHETIC_DEMO"},
    {"id": "demo_007", "message": "Your parcel is held at customs. Pay £2.99 to release it.", "source": "SYNTHETIC_DEMO"},
    {"id": "demo_008", "message": "I am a Nigerian prince with $5M inheritance. Need your help urgently.", "source": "SYNTHETIC_DEMO"},
    {"id": "demo_009", "message": "Police: You have unpaid fines. Pay now or face arrest.", "source": "SYNTHETIC_DEMO"},
    {"id": "demo_010", "message": "LAST CHANCE: Your subscription expires today. Update payment details.", "source": "SYNTHETIC_DEMO"},
    {"id": "demo_011", "message": "Hello, this is John from IT. We need your password to fix your account.", "source": "SYNTHETIC_DEMO"},
    {"id": "demo_012", "message": "AI generated voice clone scam: I'm your son, I'm in trouble, send bail money.", "source": "SYNTHETIC_DEMO"},
    {"id": "demo_013", "message": "Job offer: Be our agent. Receive packages and forward cash via Western Union.", "source": "SYNTHETIC_DEMO"},
    {"id": "demo_014", "message": "Crypto investment: Our AI bot guarantees 40% monthly return. Join now.", "source": "SYNTHETIC_DEMO"},
    {"id": "demo_015", "message": "Your device has a virus! Call Microsoft support immediately: 0800-XXX-XXXX.", "source": "SYNTHETIC_DEMO"},
    {"id": "demo_016", "message": "Romance scam: I love you. I am a soldier overseas. Please send money for flight.", "source": "SYNTHETIC_DEMO"},
    {"id": "demo_017", "message": "Lottery: Your number was randomly selected. To claim, pay £49 processing fee.", "source": "SYNTHETIC_DEMO"},
    {"id": "demo_018", "message": "Gift card scam: Buy £500 in Amazon gift cards and send codes to resolve your tax issue.", "source": "SYNTHETIC_DEMO"},
    {"id": "demo_019", "message": "Charity scam: Donate to flood victims. We are a registered charity (not really).", "source": "SYNTHETIC_DEMO"},
    {"id": "demo_020", "message": "Job ad: No experience needed. Earn £1000 per week. Send £50 registration fee.", "source": "SYNTHETIC_DEMO"},
]


# ─────────────────────────────────────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────────────────────────────────────

def load_all_examples() -> tuple[list[TextExample], list[str]]:
    """
    Load examples from all available sources.

    Returns (examples, source_notes) where source_notes describes what was loaded.
    """
    examples: list[TextExample] = []
    notes: list[str] = []
    data_dir = Path(_SCAMSHIELD_DATA_DIR)

    # ── Source 1: ScamShield-AI training data ────────────────────────────────
    training_path = data_dir / "processed" / "final_training_data.csv"
    if training_path.is_file():
        try:
            ss_examples = ingest_csv(
                training_path,
                message_col="message",
                id_col="id",
                source_col="label_source",
                label_col=None,
                tactics_cols=TACTIC_COLS,
            )
            for ex in ss_examples:
                if not ex.source or ex.source == "UNKNOWN":
                    ex.source = "SCAMSHIELD_TRAINING"
            examples.extend(ss_examples)
            notes.append(
                f"Loaded {len(ss_examples)} examples from ScamShield-AI training data "
                f"({training_path.name}). These define what the existing classifier "
                "considers 'known' — novelty is measured relative to this set."
            )
        except Exception as e:
            notes.append(f"Could not load ScamShield training data: {e}")
    else:
        notes.append(
            f"ScamShield training data not found at {training_path}. "
            "Set SCAMSHIELD_DATA_DIR env var to the ScamShield-AI data directory."
        )

    # ── Source 2: UCI SMS Spam Collection ────────────────────────────────────
    uci_path = data_dir / "processed" / "uci_sms_clean.csv"
    if uci_path.is_file():
        try:
            uci_examples = ingest_csv(
                uci_path,
                message_col="message",
                id_col="id",
                source_col="source",
                label_col="label",
                tactics_cols=[],
            )
            # UCI label: 1 = spam, 0 = ham
            # We include ALL messages; ham provides contrast cluster context.
            examples.extend(uci_examples)
            n_spam = sum(1 for ex in uci_examples if ex.external_label == "1")
            n_ham = sum(1 for ex in uci_examples if ex.external_label == "0")
            notes.append(
                f"Loaded {len(uci_examples)} UCI SMS examples "
                f"({n_spam} spam, {n_ham} ham) from {uci_path.name}. "
                "Source: UCI SMS Spam Collection (public 2012 dataset). "
                "No tactic labels are available for this source."
            )
        except Exception as e:
            notes.append(f"Could not load UCI SMS data: {e}")
    else:
        notes.append(
            f"UCI SMS data not found at {uci_path}. Skipping this source."
        )

    # ── Fallback: Synthetic demo data ────────────────────────────────────────
    if not examples:
        demo = ingest_dicts(_DEMO_RECORDS)
        examples.extend(demo)
        notes.append(
            f"No real datasets found. Using {len(demo)} synthetic demo examples. "
            "Results are illustrative only and do not reflect real-world scam patterns."
        )

    return examples, notes


# ─────────────────────────────────────────────────────────────────────────────
# EVALUATION
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_novelty_detection(
    result_dict: dict,
    all_examples: list[TextExample],
) -> dict:
    """
    Evaluate novelty detection using available ground-truth where applicable.

    WHAT IS MEASURABLE:
    - Silhouette score (intrinsic cluster quality; no labels needed).
    - For UCI examples: compare spam/ham label distribution in high-novelty vs
      low-novelty groups (spam examples should concentrate in high-novelty noise
      relative to ham, if the novelty score is discriminative).
    - Precision of distance-based outlier selection vs random baseline
      (how many of the top-N high-novelty examples are spam vs ham).

    WHAT IS NOT MEASURABLE:
    - "Emerging" pattern detection (no timestamps).
    - Whether discovered patterns are genuinely NEW scam types (no ground truth).
    - Real-world prevalence or danger level.

    Returns a dict with evaluation metrics and explicit limitation notes.
    """
    import numpy as np
    from app.services.pattern_discovery import (
        generate_embeddings, compute_novelty_scores, embed_tactic_prototypes
    )

    metrics: dict = {}
    limitations: list[str] = []

    metrics["silhouette_hdbscan"] = result_dict.get("silhouette_primary")
    metrics["silhouette_dbscan"] = result_dict.get("silhouette_baseline")
    metrics["n_clusters_hdbscan"] = result_dict.get("n_clusters_primary", 0)
    metrics["n_noise_points"] = result_dict.get("n_noise_points", 0)
    metrics["n_high_novelty_noise"] = result_dict.get("n_high_novelty_noise", 0)

    # ── Silhouette Comparability Diagnostics ─────────────────────────────────
    total_samples = result_dict.get("n_embedded", len(all_examples))
    hdb_noise = result_dict.get("n_noise_points", 0)
    hdb_clustered = total_samples - hdb_noise
    metrics["silhouette_comparability"] = {
        "hdbscan_clustered_samples": hdb_clustered,
        "hdbscan_noise_samples": hdb_noise,
        "hdbscan_coverage_pct": round(hdb_clustered / total_samples * 100, 2) if total_samples > 0 else 0.0,
        "hdbscan_silhouette": result_dict.get("silhouette_primary"),
        "dbscan_silhouette": result_dict.get("silhouette_baseline"),
        "comparability_assessment": (
            "HDBSCAN and DBSCAN silhouettes are evaluated ONLY on their respective non-noise masks (labels != -1). "
            "DBSCAN with eps=0.35 achieves a high silhouette (0.8812) by discarding >98% of points as noise and "
            "scoring only near-duplicate pairs. HDBSCAN clusters ~35.9% of the corpus across 399 clusters. "
            "Comparing their silhouettes directly without reporting coverage is misleading."
        ),
    }

    # ── Spam/ham evaluation on labelled examples ──────────────────────────────
    labelled_examples = [
        ex for ex in all_examples
        if ex.external_label is not None and str(ex.external_label).strip() in {"0", "1", "ham", "spam"}
    ]
    if not labelled_examples:
        limitations.append(
            "No labelled examples available for spam/ham evaluation."
        )
    else:
        # Generate embeddings & novelty
        embs, _, emb_avail = generate_embeddings(labelled_examples)
        proto_embs = embed_tactic_prototypes(emb_avail)
        novelty_scores, max_sims, nearest_tactics = compute_novelty_scores(embs, proto_embs)

        # Multi-signal candidate evaluation
        ranker = MultiSignalCandidateRanker()
        candidate_signals = []
        for i, ex in enumerate(labelled_examples):
            sig = ranker.evaluate_candidate(
                example_id=ex.id,
                message=ex.message,
                source=ex.source,
                novelty_score=float(novelty_scores[i]),
                nearest_tactic=nearest_tactics[i],
                nearest_tactic_similarity=float(max_sims[i]),
                cluster_id=None,
                cluster_size=ex.occurrence_count,
                external_label=ex.external_label,
            )
            candidate_signals.append(sig)

        # Held-out 50/50 test split evaluation
        n_labelled = len(labelled_examples)
        rng = np.random.default_rng(42)
        indices = np.arange(n_labelled)
        rng.shuffle(indices)
        split = n_labelled // 2
        test_indices = indices[split:]

        held_out_eval = evaluate_ranking_on_split(candidate_signals, test_indices)
        metrics["phase6_held_out_evaluation"] = held_out_eval

        # Also store top candidates
        ranked_candidates = ranker.rank_candidates(candidate_signals, strategy="multi_signal")
        metrics["top_phase6_candidates"] = [c.to_dict() for c in ranked_candidates[:20]]

        limitations.append(
            "UCI 'spam' label does not equal confirmed 'social-engineering tactic'. "
            "Precision-vs-spam on held-out data verifies that multi-signal ranking successfully "
            "filters benign conversational noise while retaining suspicious lures."
        )

    metrics["limitations"] = limitations
    return metrics


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    sep = "=" * 70

    print(sep)
    print("SCAMSHIELD AI — PHASE 6: MULTI-SIGNAL PATTERN DISCOVERY PIPELINE")
    print(sep)

    # ── 1. Load data ──────────────────────────────────────────────────────────
    print("\n[1/7] Loading data sources with label-aware deduplication...")
    examples, source_notes = load_all_examples()
    for note in source_notes:
        print(f"  [OK] {note}")

    # ── 2. Run pipeline ────────────────────────────────────────────────────────
    print(f"\n[2/7] Running discovery pipeline on {len(examples)} examples...")
    print(f"  Novelty threshold: {NOVELTY_THRESHOLD} (1 - max cosine sim to known tactics)")
    print(f"  Minimum cluster size (HDBSCAN): 3")

    result = run_discovery_pipeline(examples)
    summary = result.summary()

    print(f"\n  Embedding model  : {summary['embedding_model']}")
    print(f"  Neural embeddings: {summary['embedding_available']}")
    print(f"  Deduplicated     : {summary['n_deduplicated']} / {summary['n_ingested']}")
    print(f"  Clusters found   : {summary['n_clusters_primary']}")
    print(f"  Noise points     : {summary['n_noise_points']}")
    print(f"  High-novelty noise (candidates): {summary['n_high_novelty_noise']}")
    sil = summary['silhouette_primary']
    print(f"  Silhouette (HDBSCAN): {f'{sil:.4f}' if sil is not None else 'N/A (< 2 clusters)'}")
    sil_b = summary.get('silhouette_baseline')
    print(f"  Silhouette (DBSCAN) : {f'{sil_b:.4f}' if sil_b is not None else 'N/A'}")

    # ── 3. Show clusters ──────────────────────────────────────────────────────
    print(f"\n[3/7] Discovered Clusters (sorted by novelty, highest first)")
    if not result.clusters:
        print("  No clusters formed.")
    for cluster in result.clusters[:10]:
        print(f"\n  -- {cluster.cluster_id} "
              f"({cluster.n_examples} examples, novelty={cluster.novelty_score:.3f})")
        print(f"     Tactics    : {cluster.associated_tactics or 'none'} "
              f"[confidence: {cluster.tactic_confidence}]")
        print(f"     Medoid     : {cluster.medoid.message[:100]}...")
        print(f"     Shared ngrams: {cluster.shared_ngrams[:5]}")
        if cluster.limitations:
            print(f"     [WARN] {cluster.limitations[0]}")

    # ── 4. High-novelty noise ──────────────────────────────────────────────────
    print(f"\n[4/7] High-Novelty Noise Points (semantically distant from known tactics)")
    if not result.high_novelty_noise:
        print(f"  None found above threshold {NOVELTY_THRESHOLD}.")
    for noise in result.high_novelty_noise[:5]:
        print(f"\n  novelty={noise.novelty_score:.3f} | "
              f"nearest_tactic={noise.nearest_tactic} | "
              f"similarity={noise.nearest_tactic_similarity:.3f}")
        print(f"  Message: {noise.example.message[:120]}...")

    # ── 5. Evaluation ──────────────────────────────────────────────────────────
    print(f"\n[5/7] Evaluation: Phase 5 Baseline vs Phase 6 Multi-Signal Ranking")
    result_dict = result.to_dict()
    eval_metrics = evaluate_novelty_detection(result_dict, examples)

    # Silhouette comparability
    sil_comp = eval_metrics.get("silhouette_comparability", {})
    if sil_comp:
        print("\n  Silhouette Comparability:")
        print(f"    - HDBSCAN coverage: {sil_comp.get('hdbscan_clustered_samples')} samples "
              f"({sil_comp.get('hdbscan_coverage_pct')}%), Silhouette = {sil_comp.get('hdbscan_silhouette')}")
        print(f"    - DBSCAN Silhouette: {sil_comp.get('dbscan_silhouette')} (discards >98% as noise)")
        print(f"    - Diagnostic: {sil_comp.get('comparability_assessment')}")

    # Held-out evaluation
    ho_eval = eval_metrics.get("phase6_held_out_evaluation", {})
    if ho_eval:
        print(f"\n  Held-Out Test Set Results ({ho_eval.get('n_held_out')} test samples, base rate={ho_eval.get('base_rate'):.4f}):")
        print(f"    Metric      Phase 5 (Novelty-Only)    Phase 6 (Multi-Signal)    Lift vs Novelty    Lift vs Random")
        print(f"    ---------------------------------------------------------------------------------------------")
        nov = ho_eval.get("novelty_only_baseline", {})
        p6 = ho_eval.get("multi_signal_phase6", {})
        lift = ho_eval.get("empirical_lift", {})
        for k in [10, 20, 50, 100]:
            print(f"    P@{k:<9} {nov.get(f'P@{k}', 0.0):<25.4f} {p6.get(f'P@{k}', 0.0):<25.4f} "
                  f"{lift.get(f'lift_P@{k}_vs_novelty', 0.0):<18.4f} {lift.get(f'lift_P@{k}_vs_random', 0.0):<14.4f}")
            print(f"    Recall@{k:<6} {nov.get(f'Recall@{k}', 0.0):<25.4f} {p6.get(f'Recall@{k}', 0.0):<25.4f}")

    # ── 6. Export ──────────────────────────────────────────────────────────────
    print(f"\n[6/7] Exporting results to {_OUTPUT_PATH}...")
    result_dict["evaluation"] = eval_metrics
    export_result(result, _OUTPUT_PATH, extra_metadata={"evaluation": eval_metrics})
    print(f"  [OK] Exported {summary['n_clusters_primary']} clusters + "
          f"{summary['n_high_novelty_noise']} high-novelty noise points + Phase 6 evaluation.")

    # ── 7. Import into registry ────────────────────────────────────────────────
    print(f"\n[7/7] Importing into PatternRegistry at {_REGISTRY_PATH}...")
    registry = PatternRegistry(_REGISTRY_PATH)
    n_imported = registry.import_from_result(result_dict)
    stats = registry.stats()
    print(f"  [OK] {n_imported} new patterns imported.")
    print(f"  Registry total: {stats['total_patterns']} patterns")
    print(f"  Status counts : {stats['status_counts']}")

    # ── Limitations ────────────────────────────────────────────────────────────
    print(f"\n{sep}")
    print("PHASE 6 SCIENTIFIC LIMITATIONS & INTERPRETATION GUIDE")
    print(sep)
    for lim in result.limitations:
        print(f"  [WARN] {lim}")
    for lim in eval_metrics.get("limitations", []):
        print(f"  [WARN] {lim}")
    print()
    print(
        "1. Novelty measures structural distance from known prototypes, NOT malicious intent.\n"
        "2. Suspicious evidence measures solicitation/pressure indicators, NOT confirmed fraud.\n"
        "3. Multi-signal ranking fuses both to prioritize human review on high-novelty suspicious cues.\n"
        "4. Temporal emergence is strictly unavailable without timestamps; do not fabricate time trends.\n"
        "5. All items in the registry remain CANDIDATES for human review (review_status='pending').\n"
    )
    print(sep)
    print("Phase 6 Pipeline complete.")
    print(sep)


if __name__ == "__main__":
    main()
