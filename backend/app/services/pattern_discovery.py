"""
pattern_discovery.py
====================
ScamShield AI – Phase 5: Emerging Social-Engineering Pattern Discovery

Implements a modular, reproducible pipeline for discovering candidate emerging
scam patterns from unlabelled or partially-labelled text corpora.

DESIGN PRINCIPLES
-----------------
- Each concept is implemented separately and documented:
    * Novel to current reference dataset ≠ semantically distant from known patterns
      ≠ a newly forming cluster ≠ a pattern increasing in frequency over time.
- Temporal emergence is NOT claimed. Timestamps are not invented.
- Evidence claims are grounded only in what the data supports.
- Uncertainty flags and limitations are explicit throughout.
- Embedding model unavailability is handled gracefully (no silent crash).
- Results are always flagged for human review; no automatic model updates.

ALGORITHM SELECTION RATIONALE
------------------------------
Given a dataset of O(100–5000) SMS-length text messages:
  - HDBSCAN (sklearn ≥ 1.3, available here): density-based, no K required,
    handles noise as label –1, variable cluster sizes. PRIMARY algorithm.
  - DBSCAN: grid-searchable epsilon baseline. Compared for cluster quality.
  - AgglomerativeClustering (ward): deterministic fallback for N < MIN_HDBSCAN.
  - KMeans: NOT used — assumes equal-density spherical clusters, unsuitable here.

For N < MIN_SAMPLES_FOR_CLUSTERING no clustering is attempted; each example is
returned as an individual noise point with a note explaining the limitation.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS & THRESHOLDS
# ─────────────────────────────────────────────────────────────────────────────

MIN_SAMPLES_FOR_CLUSTERING = 10
"""Below this N, clustering is not attempted (too few points for density estimate)."""

HDBSCAN_MIN_CLUSTER_SIZE = 3
"""Minimum examples for HDBSCAN to form a valid cluster."""

DBSCAN_EPS = 0.35
"""Cosine-distance epsilon for DBSCAN baseline comparison."""

DBSCAN_MIN_SAMPLES = 2

NOVELTY_THRESHOLD = 0.65
"""Max cosine similarity to ANY known tactic prototype below which a message
is considered 'semantically distant from known patterns'.
This is a distance threshold, NOT a fraud probability threshold."""

TACTIC_ALIGNMENT_THRESHOLD = 0.45
"""If a cluster's median similarity to a tactic prototype exceeds this, the
cluster is associated with that tactic (with stated confidence 'supported')."""

SUPPORTED_SOURCES = {"UCI_SMS", "MANUAL", "IMPORT", "SYNTHETIC_DEMO"}
"""Known provenance labels that may appear in ingested datasets."""

# These are the social-engineering tactic prototypes used as reference anchors.
# They are the same prototypes used in the original semantic_candidates.py
# (ScamShield-AI repository). Duplicated here to make this service self-contained.
TACTIC_PROTOTYPES: dict[str, str] = {
    "authority": (
        "A message claiming to represent a bank, government agency, "
        "police department, company, official organization or authority."
    ),
    "urgency": (
        "A message pressuring the recipient to act immediately, "
        "quickly, today, or before a deadline."
    ),
    "threat": (
        "A message threatening account suspension, penalties, fines, "
        "legal action, arrest, cancellation or other negative consequences."
    ),
    "fear": (
        "A message attempting to create fear or anxiety by warning "
        "about fraud, hacking, security problems, stolen information "
        "or dangerous consequences."
    ),
    "impersonation": (
        "A message pretending to be a trusted person, bank, company, "
        "government organization, police officer or official service."
    ),
    "credential_request": (
        "A message asking for passwords, PINs, OTPs, verification codes, "
        "login information, security codes or authentication credentials."
    ),
    "payment_request": (
        "A message requesting money, payment, transfer, deposit, fees "
        "or financial transactions."
    ),
    "reward_lure": (
        "A message enticing the recipient with prizes, winnings, rewards, "
        "free offers, bonuses, cash or gifts."
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TextExample:
    """A single text example with provenance metadata and stable ID."""
    id: str
    message: str
    source: str = "UNKNOWN"
    external_label: str | None = None   # e.g. "spam" / "ham" from UCI, or None
    known_tactics: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    sources: set[str] = field(default_factory=set)
    occurrence_count: int = 1
    label_conflict: bool = False

    def __post_init__(self) -> None:
        # Guarantee stable ID: if not provided, derive from message hash
        if not self.id:
            self.id = self._compute_hash(self.message)
        if not self.sources and self.source:
            self.sources = {self.source}

    @staticmethod
    def _compute_hash(text: str) -> str:
        return "hash_" + hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]


@dataclass
class DiscoveredCluster:
    """One discovered cluster of messages from the pipeline."""
    cluster_id: str
    algorithm: str
    examples: list[TextExample]
    medoid_idx: int                     # index into self.examples
    centroid_embedding: np.ndarray | None
    novelty_score: float                # 1 - max cosine sim to ANY tactic prototype
    associated_tactics: list[str]       # tactics with sim > TACTIC_ALIGNMENT_THRESHOLD
    tactic_confidence: str              # "supported" | "weak" | "none"
    shared_ngrams: list[str]
    review_status: str = "pending"      # pending | known | potentially_novel | benign | inconclusive
    limitations: list[str] = field(default_factory=list)

    @property
    def n_examples(self) -> int:
        return len(self.examples)

    @property
    def medoid(self) -> TextExample:
        return self.examples[self.medoid_idx]

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "algorithm": self.algorithm,
            "n_examples": self.n_examples,
            "novelty_score": round(self.novelty_score, 4),
            "associated_tactics": self.associated_tactics,
            "tactic_confidence": self.tactic_confidence,
            "review_status": self.review_status,
            "medoid": {
                "id": self.medoid.id,
                "message": self.medoid.message,
                "source": self.medoid.source,
            },
            "representative_examples": [
                {
                    "id": ex.id,
                    "message": ex.message,
                    "source": ex.source,
                    "external_label": ex.external_label,
                }
                for ex in self.examples[:5]
            ],
            "shared_ngrams": self.shared_ngrams[:10],
            "limitations": self.limitations,
        }


@dataclass
class NoisePoint:
    """A message that did not belong to any cluster (HDBSCAN noise label –1)."""
    example: TextExample
    novelty_score: float
    nearest_tactic: str | None
    nearest_tactic_similarity: float


@dataclass
class DiscoveryResult:
    """Complete result from one pipeline run."""
    n_ingested: int
    n_deduplicated: int
    n_embedded: int
    embedding_model: str
    algorithm_primary: str
    algorithm_baseline: str | None
    clusters: list[DiscoveredCluster]
    noise_points: list[NoisePoint]
    high_novelty_noise: list[NoisePoint]  # noise points above NOVELTY_THRESHOLD
    silhouette_primary: float | None      # None if < 2 clusters or < 2 points
    silhouette_baseline: float | None
    limitations: list[str]
    embedding_available: bool

    def summary(self) -> dict[str, Any]:
        return {
            "n_ingested": self.n_ingested,
            "n_deduplicated": self.n_deduplicated,
            "n_embedded": self.n_embedded,
            "embedding_model": self.embedding_model,
            "embedding_available": self.embedding_available,
            "algorithm_primary": self.algorithm_primary,
            "n_clusters_primary": len(self.clusters),
            "n_noise_points": len(self.noise_points),
            "n_high_novelty_noise": len(self.high_novelty_noise),
            "silhouette_primary": self.silhouette_primary,
            "silhouette_baseline": self.silhouette_baseline,
            "limitations": self.limitations,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.summary(),
            "clusters": [c.to_dict() for c in self.clusters],
            "high_novelty_noise_examples": [
                {
                    "id": n.example.id,
                    "message": n.example.message,
                    "source": n.example.source,
                    "novelty_score": round(n.novelty_score, 4),
                    "nearest_tactic": n.nearest_tactic,
                    "nearest_tactic_similarity": round(n.nearest_tactic_similarity, 4),
                }
                for n in self.high_novelty_noise[:20]
            ],
        }


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 1 — INGESTION
# ─────────────────────────────────────────────────────────────────────────────

def ingest_csv(
    csv_path: str | Path,
    message_col: str = "message",
    id_col: str | None = "id",
    source_col: str | None = "source",
    label_col: str | None = "label",
    tactics_cols: list[str] | None = None,
    max_rows: int | None = None,
) -> list[TextExample]:
    """
    Ingest a CSV file into a list of TextExample objects.

    Parameters
    ----------
    csv_path : path to a UTF-8 CSV file.
    message_col : column name containing the text.
    id_col : optional column for stable row identifiers.
    source_col : optional column for provenance label.
    label_col : optional column for an external binary/class label (e.g. spam/ham).
    tactics_cols : optional list of tactic columns (binary 0/1) to read.
    max_rows : optional row limit (for testing).

    Returns
    -------
    list[TextExample]
    """
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"Dataset not found: {csv_path}")

    examples: list[TextExample] = []
    tactics_cols = tactics_cols or []

    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh)
        if message_col not in (reader.fieldnames or []):
            raise ValueError(
                f"Column '{message_col}' not found. "
                f"Available columns: {reader.fieldnames}"
            )

        for i, row in enumerate(reader):
            if max_rows is not None and i >= max_rows:
                break

            raw_message = row.get(message_col, "").strip()
            if not raw_message:
                continue

            row_id = row.get(id_col, "").strip() if id_col else ""
            source = row.get(source_col, "UNKNOWN").strip() if source_col else "UNKNOWN"
            ext_label = row.get(label_col, None) if label_col else None

            known_tactics = []
            for tc in tactics_cols:
                val = row.get(tc, "0").strip()
                try:
                    if float(val) >= 0.5:
                        known_tactics.append(tc)
                except ValueError:
                    pass

            examples.append(TextExample(
                id=row_id,
                message=raw_message,
                source=source,
                external_label=str(ext_label).strip() if ext_label is not None else None,
                known_tactics=known_tactics,
                metadata={"row_index": i},
            ))

    return examples


def ingest_dicts(records: list[dict[str, Any]]) -> list[TextExample]:
    """
    Ingest a list of dicts directly (for API / in-memory use).
    Each dict must have at minimum a 'message' key.
    An 'id', 'source', 'external_label', 'known_tactics' key are optional.
    """
    examples: list[TextExample] = []
    for i, rec in enumerate(records):
        message = str(rec.get("message", "")).strip()
        if not message:
            continue
        examples.append(TextExample(
            id=str(rec.get("id", "")),
            message=message,
            source=str(rec.get("source", "IMPORT")),
            external_label=rec.get("external_label", None),
            known_tactics=list(rec.get("known_tactics", [])),
            metadata={"record_index": i, **{
                k: v for k, v in rec.items()
                if k not in {"id", "message", "source", "external_label", "known_tactics"}
            }},
        ))
    return examples


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 2 — NORMALIZATION & DEDUPLICATION
# ─────────────────────────────────────────────────────────────────────────────

_WHITESPACE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """
    Conservative normalization for scam-text analysis.

    Preserves:
    - Capitalisation (ALL CAPS may be meaningful evidence of urgency).
    - Punctuation (exclamation marks, question marks are evidence signals).
    - URLs and phone numbers (important provenance signals).
    - Numbers (account numbers, prize amounts, etc.).

    Removes:
    - Leading / trailing whitespace.
    - Repeated internal whitespace.
    - Non-printable control characters.
    - Unicode compatibility normalization (NFC form).
    """
    text = unicodedata.normalize("NFC", text)
    # Remove non-printable characters except newline/tab (map them to space)
    text = "".join(
        " " if unicodedata.category(ch) in ("Cc", "Cf") else ch
        for ch in text
    )
    text = _WHITESPACE.sub(" ", text).strip()
    return text


def deduplicate(
    examples: list[TextExample],
    *,
    normalize: bool = True,
) -> tuple[list[TextExample], int]:
    """
    Remove exact-duplicate messages (by normalized text hash).

    Returns (deduplicated_list, n_removed).
    First occurrence is kept as the canonical representation, but metadata
    from duplicates is merged:
      - Provenance sources are accumulated in `canonical.sources`
      - Duplicate count is tracked in `canonical.occurrence_count`
      - External labels are aligned (if canonical had None and duplicate had a label,
        the label is preserved)
      - Conflicting external labels (e.g. 0 vs 1) are detected and flagged with
        `canonical.label_conflict = True`
      - Known tactic labels are merged (union of tags)
    """
    seen_map: dict[str, TextExample] = {}
    unique: list[TextExample] = []
    n_removed = 0

    for ex in examples:
        key_text = normalize_text(ex.message) if normalize else ex.message
        h = hashlib.md5(key_text.encode("utf-8", errors="replace")).hexdigest()
        if h in seen_map:
            n_removed += 1
            canonical = seen_map[h]
            canonical.occurrence_count += 1
            if ex.source:
                canonical.sources.add(ex.source)
                canonical.metadata["all_sources"] = sorted(canonical.sources)
            
            # Label alignment: if canonical has no external label, inherit from duplicate
            if canonical.external_label is None and ex.external_label is not None:
                canonical.external_label = ex.external_label
            elif (
                canonical.external_label is not None
                and ex.external_label is not None
                and str(canonical.external_label).strip() != str(ex.external_label).strip()
            ):
                canonical.label_conflict = True
                canonical.metadata["conflicting_labels"] = [
                    canonical.external_label,
                    ex.external_label,
                ]

            # Merge tactic annotations
            if ex.known_tactics:
                merged_tactics = set(canonical.known_tactics).union(ex.known_tactics)
                canonical.known_tactics = sorted(merged_tactics)
        else:
            if not ex.sources and ex.source:
                ex.sources = {ex.source}
            seen_map[h] = ex
            unique.append(ex)

    return unique, n_removed


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 3 — EMBEDDING
# ─────────────────────────────────────────────────────────────────────────────

EMBEDDING_DIM = 384
_EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def _embed_texts_fastembed(texts: list[str]) -> np.ndarray:
    """Embed texts using the existing fastembed service (384-dim MiniLM)."""
    from app.services.embedding_service import embed_texts
    embeddings = embed_texts(texts)
    # L2-normalize for cosine similarity
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return embeddings / norms


def _embed_texts_fallback(texts: list[str]) -> np.ndarray:
    """
    Deterministic TF-IDF SVD fallback embedding for when fastembed is unavailable.

    Used ONLY in tests or offline mode. Dimension is fixed at EMBEDDING_DIM.
    Quality is lower than neural embeddings; results are clearly marked
    'embedding_available: False' in the DiscoveryResult.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.decomposition import TruncatedSVD
    from sklearn.preprocessing import normalize as sk_normalize

    n = len(texts)
    n_components = min(EMBEDDING_DIM, n - 1, 100)
    if n_components < 2:
        # Trivially return zero embeddings — caller handles this
        return np.zeros((n, EMBEDDING_DIM), dtype="float32")

    vec = TfidfVectorizer(max_features=5000, ngram_range=(1, 2), sublinear_tf=True)
    X = vec.fit_transform(texts)

    svd = TruncatedSVD(n_components=n_components, random_state=42)
    reduced = svd.fit_transform(X).astype("float32")

    # Pad to EMBEDDING_DIM
    padded = np.zeros((n, EMBEDDING_DIM), dtype="float32")
    padded[:, :n_components] = reduced
    return sk_normalize(padded)


def generate_embeddings(
    examples: list[TextExample],
) -> tuple[np.ndarray, str, bool]:
    """
    Generate L2-normalized semantic embeddings for a list of TextExample objects.

    Returns
    -------
    (embeddings, model_name, embedding_available)
    - embeddings: shape (N, EMBEDDING_DIM), float32, L2-normalized
    - model_name: human-readable string identifying the model used
    - embedding_available: True if neural model was used, False if fallback
    """
    texts = [normalize_text(ex.message) for ex in examples]

    try:
        embeddings = _embed_texts_fastembed(texts)
        return embeddings, _EMBEDDING_MODEL_NAME, True
    except Exception as fastembed_err:
        # Fallback: TF-IDF SVD
        embeddings = _embed_texts_fallback(texts)
        return embeddings, f"tfidf-svd-fallback (fastembed error: {fastembed_err})", False


def embed_tactic_prototypes(
    embedding_available: bool,
) -> dict[str, np.ndarray]:
    """
    Embed the TACTIC_PROTOTYPES using the same model as the example embeddings.

    Returns a dict tactic_name → L2-normalized 1D embedding (EMBEDDING_DIM,).
    Falls back consistently with generate_embeddings.
    """
    names = list(TACTIC_PROTOTYPES.keys())
    texts = list(TACTIC_PROTOTYPES.values())

    if embedding_available:
        try:
            embs = _embed_texts_fastembed(texts)
        except Exception:
            embs = _embed_texts_fallback(texts)
    else:
        embs = _embed_texts_fallback(texts)

    return {name: embs[i] for i, name in enumerate(names)}


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 4 — CLUSTERING
# ─────────────────────────────────────────────────────────────────────────────

def _safe_silhouette(X: np.ndarray, labels: np.ndarray) -> float | None:
    """Compute silhouette score; return None if not computable."""
    unique = set(labels.tolist())
    # silhouette requires >= 2 distinct non-noise labels and >= 2 points
    non_noise = [l for l in unique if l != -1]
    if len(non_noise) < 2 or len(X) < 2:
        return None
    # Only score non-noise points
    mask = labels != -1
    if mask.sum() < 2:
        return None
    try:
        from sklearn.metrics import silhouette_score
        return float(silhouette_score(X[mask], labels[mask], metric="cosine"))
    except Exception:
        return None


def _run_hdbscan(X: np.ndarray, min_cluster_size: int) -> np.ndarray:
    from sklearn.cluster import HDBSCAN
    clusterer = HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=1,
        metric="euclidean",  # on L2-normalized vectors, euclidean ≈ cosine
        cluster_selection_method="eom",
    )
    return clusterer.fit_predict(X)


def _run_dbscan(X: np.ndarray) -> np.ndarray:
    from sklearn.cluster import DBSCAN
    clusterer = DBSCAN(
        eps=DBSCAN_EPS,
        min_samples=DBSCAN_MIN_SAMPLES,
        metric="euclidean",
    )
    return clusterer.fit_predict(X)


def _run_agglomerative(X: np.ndarray, n_clusters: int) -> np.ndarray:
    from sklearn.cluster import AgglomerativeClustering
    clusterer = AgglomerativeClustering(
        n_clusters=n_clusters,
        metric="cosine",
        linkage="average",
    )
    return clusterer.fit_predict(X)


def run_clustering(
    embeddings: np.ndarray,
    n: int,
) -> tuple[np.ndarray, np.ndarray | None, str, str | None, float | None, float | None]:
    """
    Run primary (HDBSCAN) and baseline (DBSCAN) clustering on L2-normalized embeddings.

    Returns
    -------
    (primary_labels, baseline_labels, primary_name, baseline_name,
     primary_silhouette, baseline_silhouette)
    """
    if n < MIN_SAMPLES_FOR_CLUSTERING:
        # Not enough points for reliable density-based clustering
        labels = np.full(n, -1, dtype=int)  # all noise
        return labels, None, "none (too few samples)", None, None, None

    # Primary: HDBSCAN
    primary_labels = _run_hdbscan(embeddings, min_cluster_size=HDBSCAN_MIN_CLUSTER_SIZE)
    primary_sil = _safe_silhouette(embeddings, primary_labels)

    # Baseline: DBSCAN
    baseline_labels = _run_dbscan(embeddings)
    baseline_sil = _safe_silhouette(embeddings, baseline_labels)

    return (
        primary_labels,
        baseline_labels,
        "HDBSCAN(min_cluster_size=3)",
        f"DBSCAN(eps={DBSCAN_EPS}, min_samples={DBSCAN_MIN_SAMPLES})",
        primary_sil,
        baseline_sil,
    )


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 5 — NOVELTY SCORING
# ─────────────────────────────────────────────────────────────────────────────

def compute_novelty_scores(
    embeddings: np.ndarray,
    prototype_embeddings: dict[str, np.ndarray],
) -> tuple[np.ndarray, np.ndarray, list[str | None]]:
    """
    For each embedding, compute:
    - max cosine similarity to any tactic prototype
    - novelty score = 1 – max_similarity

    Returns
    -------
    (novelty_scores, max_similarities, nearest_tactics)
    All arrays have shape (N,).
    """
    if not prototype_embeddings:
        n = len(embeddings)
        return np.ones(n, dtype="float32"), np.zeros(n, dtype="float32"), [None] * n

    tactic_names = list(prototype_embeddings.keys())
    proto_matrix = np.stack([prototype_embeddings[t] for t in tactic_names], axis=0)  # (T, D)

    # Cosine similarity (embeddings and prototypes are already L2-normalized)
    sims = embeddings @ proto_matrix.T  # (N, T)

    max_sims = sims.max(axis=1)          # (N,)
    nearest_idxs = sims.argmax(axis=1)   # (N,)
    nearest_tactics: list[str | None] = [tactic_names[i] for i in nearest_idxs.tolist()]
    novelty_scores = 1.0 - max_sims

    return novelty_scores.astype("float32"), max_sims.astype("float32"), nearest_tactics


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 6 — CLUSTER DESCRIPTION
# ─────────────────────────────────────────────────────────────────────────────

def _extract_ngrams(texts: list[str], max_features: int = 20) -> list[str]:
    """Extract the most frequent content n-grams across a set of texts."""
    if not texts:
        return []
    try:
        from sklearn.feature_extraction.text import CountVectorizer
        vec = CountVectorizer(
            ngram_range=(1, 2),
            max_features=max_features,
            stop_words="english",
            token_pattern=r"(?u)\b\w\w+\b",
        )
        vec.fit(texts)
        return list(vec.vocabulary_.keys())
    except Exception:
        return []


def _find_medoid(embeddings: np.ndarray) -> int:
    """
    Find the index of the medoid — the example whose embedding is closest
    to the mean of the cluster (most representative single point).
    """
    centroid = embeddings.mean(axis=0)
    centroid /= (np.linalg.norm(centroid) + 1e-9)
    sims = embeddings @ centroid
    return int(sims.argmax())


def describe_cluster(
    cluster_examples: list[TextExample],
    cluster_embeddings: np.ndarray,
    prototype_embeddings: dict[str, np.ndarray],
    cluster_id: str,
    algorithm: str,
    cluster_novelty_scores: np.ndarray,
) -> DiscoveredCluster:
    """Build a DiscoveredCluster descriptor from cluster members."""
    # Medoid
    medoid_idx = _find_medoid(cluster_embeddings)

    # Centroid embedding
    centroid = cluster_embeddings.mean(axis=0)
    norm = np.linalg.norm(centroid)
    centroid = centroid / (norm + 1e-9)

    # Tactic association via centroid–prototype cosine similarity
    associated_tactics: list[str] = []
    tactic_sims: dict[str, float] = {}
    for tactic, proto_emb in prototype_embeddings.items():
        sim = float(np.dot(centroid, proto_emb))
        tactic_sims[tactic] = sim
        if sim >= TACTIC_ALIGNMENT_THRESHOLD:
            associated_tactics.append(tactic)

    max_tactic_sim = max(tactic_sims.values()) if tactic_sims else 0.0
    if max_tactic_sim >= TACTIC_ALIGNMENT_THRESHOLD:
        tactic_confidence = "supported"
    elif max_tactic_sim >= 0.30:
        tactic_confidence = "weak"
    else:
        tactic_confidence = "none"

    # Cluster novelty (median of member novelty scores)
    cluster_novelty = float(np.median(cluster_novelty_scores))

    # Shared n-grams
    texts = [ex.message for ex in cluster_examples]
    shared_ngrams = _extract_ngrams(texts)

    limitations: list[str] = []
    if len(cluster_examples) < 5:
        limitations.append(
            f"Cluster contains only {len(cluster_examples)} examples. "
            "Patterns observed in very small clusters are unreliable."
        )
    if tactic_confidence == "none":
        limitations.append(
            "No close match to any known tactic prototype. "
            "This cluster may represent a novel pattern OR be noise/mixed content. "
            "Human review is required."
        )
    if tactic_confidence == "weak":
        limitations.append(
            "Weak match to a known tactic prototype. "
            "Association is uncertain and should not be reported as confirmed."
        )

    return DiscoveredCluster(
        cluster_id=cluster_id,
        algorithm=algorithm,
        examples=cluster_examples,
        medoid_idx=medoid_idx,
        centroid_embedding=centroid,
        novelty_score=cluster_novelty,
        associated_tactics=associated_tactics,
        tactic_confidence=tactic_confidence,
        shared_ngrams=shared_ngrams,
        limitations=limitations,
    )


# ─────────────────────────────────────────────────────────────────────────────
# PIPELINE ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────

def run_discovery_pipeline(
    examples: list[TextExample],
    *,
    min_cluster_size: int = HDBSCAN_MIN_CLUSTER_SIZE,
    novelty_threshold: float = NOVELTY_THRESHOLD,
    max_rows: int | None = None,
) -> DiscoveryResult:
    """
    Run the full emerging-pattern discovery pipeline on a list of TextExample objects.

    This function does NOT modify any model or registry. It returns a
    DiscoveryResult that must be saved and reviewed externally.

    Parameters
    ----------
    examples : list of TextExample (from ingest_csv or ingest_dicts)
    min_cluster_size : passed to HDBSCAN (override for small datasets)
    novelty_threshold : max cosine sim below which a point is 'semantically distant'
    max_rows : if set, only first N examples are processed (for testing)

    Returns
    -------
    DiscoveryResult
    """
    limitations: list[str] = []
    n_ingested = len(examples)

    if max_rows is not None:
        examples = examples[:max_rows]

    # ── NORMALIZE + DEDUPLICATE ───────────────────────────────────────────────
    for ex in examples:
        ex.message = normalize_text(ex.message)

    examples, n_removed = deduplicate(examples, normalize=False)  # already normalized
    n_unique = len(examples)

    if n_removed > 0:
        limitations.append(
            f"{n_removed} exact-duplicate messages were removed before clustering."
        )

    if n_unique == 0:
        return DiscoveryResult(
            n_ingested=n_ingested, n_deduplicated=0, n_embedded=0,
            embedding_model="none", algorithm_primary="none", algorithm_baseline=None,
            clusters=[], noise_points=[], high_novelty_noise=[],
            silhouette_primary=None, silhouette_baseline=None,
            limitations=["No examples remained after deduplication."],
            embedding_available=False,
        )

    # ── EMBEDDINGS ────────────────────────────────────────────────────────────
    embeddings, model_name, embedding_available = generate_embeddings(examples)

    if not embedding_available:
        limitations.append(
            "Neural embedding model (fastembed MiniLM) was unavailable. "
            "A TF-IDF SVD fallback was used. Clustering quality is reduced. "
            "Re-run with fastembed installed for better results."
        )

    proto_embeddings = embed_tactic_prototypes(embedding_available)

    # ── NOVELTY SCORES ────────────────────────────────────────────────────────
    novelty_scores, max_sims, nearest_tactics = compute_novelty_scores(
        embeddings, proto_embeddings
    )

    # ── CLUSTERING ────────────────────────────────────────────────────────────
    n = len(examples)
    eff_min = min(min_cluster_size, max(2, n // 5))

    (primary_labels, baseline_labels,
     primary_name, baseline_name,
     primary_sil, baseline_sil) = run_clustering(embeddings, n)

    if n < MIN_SAMPLES_FOR_CLUSTERING:
        limitations.append(
            f"Only {n} examples available; minimum for reliable density-based clustering "
            f"is {MIN_SAMPLES_FOR_CLUSTERING}. All examples treated as noise points."
        )

    # ── CLUSTER DESCRIPTORS ───────────────────────────────────────────────────
    label_to_indices: defaultdict[int, list[int]] = defaultdict(list)
    for i, lbl in enumerate(primary_labels.tolist()):
        label_to_indices[int(lbl)].append(i)

    discovered_clusters: list[DiscoveredCluster] = []
    for label, indices in sorted(label_to_indices.items()):
        if label == -1:
            continue  # noise — handled separately
        cluster_examples = [examples[i] for i in indices]
        cluster_embeddings = embeddings[indices]
        cluster_novelty = novelty_scores[indices]
        cluster_id = f"cluster_{label:03d}"

        cluster = describe_cluster(
            cluster_examples=cluster_examples,
            cluster_embeddings=cluster_embeddings,
            prototype_embeddings=proto_embeddings,
            cluster_id=cluster_id,
            algorithm=primary_name,
            cluster_novelty_scores=cluster_novelty,
        )
        discovered_clusters.append(cluster)

    # Sort clusters by novelty (most novel first — highest priority for review)
    discovered_clusters.sort(key=lambda c: -c.novelty_score)

    # ── NOISE POINTS ──────────────────────────────────────────────────────────
    noise_indices = label_to_indices.get(-1, [])
    noise_points: list[NoisePoint] = [
        NoisePoint(
            example=examples[i],
            novelty_score=float(novelty_scores[i]),
            nearest_tactic=nearest_tactics[i],
            nearest_tactic_similarity=float(max_sims[i]),
        )
        for i in noise_indices
    ]

    # High-novelty noise: semantically distant from ALL known tactic prototypes
    # These are the strongest candidates for emerging patterns but need human review.
    high_novelty_noise = [
        np for np_ in noise_points
        if np_.novelty_score >= novelty_threshold
        for np in [np_]
    ]
    high_novelty_noise.sort(key=lambda p: -p.novelty_score)

    if not discovered_clusters and not high_novelty_noise:
        limitations.append(
            "No clusters were formed and no high-novelty noise points were found. "
            "The dataset may be too small, too homogeneous, or the novelty threshold "
            "may need adjustment."
        )

    limitations.append(
        "IMPORTANT: Temporal emergence cannot be established from this dataset "
        "because no timestamps or time-separated data are available. "
        "Results describe structural novelty within the reference dataset, "
        "not real-world scam prevalence or trend."
    )

    return DiscoveryResult(
        n_ingested=n_ingested,
        n_deduplicated=n_unique,
        n_embedded=n_unique,
        embedding_model=model_name,
        algorithm_primary=primary_name,
        algorithm_baseline=baseline_name,
        clusters=discovered_clusters,
        noise_points=noise_points,
        high_novelty_noise=high_novelty_noise,
        silhouette_primary=primary_sil,
        silhouette_baseline=baseline_sil,
        limitations=limitations,
        embedding_available=embedding_available,
    )


# ─────────────────────────────────────────────────────────────────────────────
# EXPORT
# ─────────────────────────────────────────────────────────────────────────────

def export_result(
    result: DiscoveryResult,
    output_path: str | Path,
    extra_metadata: dict[str, Any] | None = None,
) -> None:
    """
    Write DiscoveryResult as a JSON file suitable for human review.

    The exported file is the input for PatternRegistry (pattern_registry.py).
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = result.to_dict()
    payload["_schema_version"] = "scamshield_discovery_v1"
    payload["_note"] = (
        "All clusters and noise points are CANDIDATES for human review. "
        "No pattern has been confirmed as a new scam type. "
        "Do not train or deploy models from unreviewed examples."
    )
    if extra_metadata:
        payload.update(extra_metadata)

    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
