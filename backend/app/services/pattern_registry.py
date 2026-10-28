"""
pattern_registry.py
====================
ScamShield AI – Phase 5: Pattern Registry and Human Review Store

Provides a JSON-backed store for discovered candidate patterns.
Reviewers can mark each pattern with one of four statuses:
  - pending        : awaiting review (default)
  - known          : matches an existing tactic; no further action needed
  - potentially_novel : looks like a new pattern; further investigation warranted
  - benign         : not a scam tactic (false positive from clustering)
  - inconclusive   : insufficient information to decide

GUARANTEES
----------
- No model is trained or updated from unreviewed entries.
- Review decisions are stored with reviewer, timestamp, and rationale.
- Registry is append-only: decisions are logged, not silently overwritten.
- Concurrent writes are not guaranteed safe (this is a research tool, not OLTP).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VALID_STATUSES = frozenset({
    "pending",
    "known",
    "potentially_novel",
    "benign",
    "inconclusive",
})

_DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "data" / "pattern_registry.json"


class PatternRegistry:
    """
    Manages the human-review registry of discovered candidate patterns.

    Parameters
    ----------
    registry_path : path to the JSON registry file. Created if absent.
    """

    def __init__(self, registry_path: str | Path | None = None) -> None:
        self.registry_path = Path(registry_path or _DEFAULT_REGISTRY_PATH)
        self._data: dict[str, Any] = self._load()

    # ─────────────────────────────────────────────────────────────────────────
    # PERSISTENCE
    # ─────────────────────────────────────────────────────────────────────────

    def _load(self) -> dict[str, Any]:
        if self.registry_path.is_file():
            try:
                with open(self.registry_path, encoding="utf-8") as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, OSError):
                return self._empty_registry()
        return self._empty_registry()

    @staticmethod
    def _empty_registry() -> dict[str, Any]:
        return {
            "_schema_version": "scamshield_registry_v1",
            "_note": (
                "This registry tracks candidate patterns discovered by the "
                "ScamShield AI pattern-discovery pipeline. "
                "No entry in this registry has been confirmed as a new scam type "
                "unless explicitly marked 'potentially_novel' by a human reviewer "
                "and subsequently validated. "
                "Do not use this file to trigger automated model updates."
            ),
            "patterns": {},
            "audit_log": [],
        }

    def save(self) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.registry_path, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, ensure_ascii=False, indent=2)

    # ─────────────────────────────────────────────────────────────────────────
    # IMPORT FROM DISCOVERY RESULT
    # ─────────────────────────────────────────────────────────────────────────

    def import_from_result(self, result_dict: dict[str, Any]) -> int:
        """
        Import discovered clusters from an exported DiscoveryResult dict.

        Only clusters not already in the registry are imported.
        Returns the number of newly imported patterns.
        """
        imported = 0
        for cluster in result_dict.get("clusters", []):
            cid = cluster["cluster_id"]
            if cid not in self._data["patterns"]:
                self._data["patterns"][cid] = {
                    "cluster_id": cid,
                    "n_examples": cluster["n_examples"],
                    "novelty_score": cluster["novelty_score"],
                    "associated_tactics": cluster["associated_tactics"],
                    "tactic_confidence": cluster["tactic_confidence"],
                    "review_status": "pending",
                    "review_history": [],
                    "medoid": cluster.get("medoid", {}),
                    "representative_examples": cluster.get("representative_examples", []),
                    "shared_ngrams": cluster.get("shared_ngrams", []),
                    "limitations": cluster.get("limitations", []),
                    "algorithm": cluster.get("algorithm", ""),
                    "import_timestamp": _utc_now(),
                    "source_provenance": list({
                        ex.get("source", "UNKNOWN")
                        for ex in cluster.get("representative_examples", [])
                    }),
                }
                imported += 1

        # Also import high-novelty noise as individually flagged items
        for noise in result_dict.get("high_novelty_noise_examples", []):
            nid = f"noise_{noise['id']}"
            if nid not in self._data["patterns"]:
                self._data["patterns"][nid] = {
                    "cluster_id": nid,
                    "n_examples": 1,
                    "novelty_score": noise["novelty_score"],
                    "associated_tactics": (
                        [noise["nearest_tactic"]] if noise.get("nearest_tactic") else []
                    ),
                    "tactic_confidence": "weak" if noise.get("nearest_tactic") else "none",
                    "review_status": "pending",
                    "review_history": [],
                    "medoid": {
                        "id": noise["id"],
                        "message": noise["message"],
                        "source": noise["source"],
                    },
                    "representative_examples": [{
                        "id": noise["id"],
                        "message": noise["message"],
                        "source": noise["source"],
                        "external_label": noise.get("external_label"),
                    }],
                    "shared_ngrams": [],
                    "limitations": [
                        "This is a single noise point, not a cluster. "
                        "No co-occurring examples were found nearby in embedding space.",
                        f"Nearest known tactic: {noise.get('nearest_tactic', 'none')} "
                        f"(similarity: {noise.get('nearest_tactic_similarity', 0):.3f}). "
                        "Low similarity to all known tactics — semantically distant.",
                    ],
                    "algorithm": "HDBSCAN_noise",
                    "import_timestamp": _utc_now(),
                    "source_provenance": [noise.get("source", "UNKNOWN")],
                }
                imported += 1

        self._audit("import", f"Imported {imported} new patterns")
        if imported:
            self.save()
        return imported

    # ─────────────────────────────────────────────────────────────────────────
    # REVIEW OPERATIONS
    # ─────────────────────────────────────────────────────────────────────────

    def review_pattern(
        self,
        pattern_id: str,
        status: str,
        reviewer: str = "anonymous",
        rationale: str = "",
    ) -> dict[str, Any]:
        """
        Record a human review decision for a pattern.

        Parameters
        ----------
        pattern_id : the cluster_id of the pattern to review.
        status : one of 'pending' | 'known' | 'potentially_novel' | 'benign' | 'inconclusive'.
        reviewer : name/ID of the reviewer (for audit trail).
        rationale : free-text explanation of the decision.

        Returns
        -------
        The updated pattern dict.

        Raises
        ------
        KeyError if pattern_id not found.
        ValueError if status is not valid.
        """
        if status not in VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{status}'. "
                f"Must be one of: {sorted(VALID_STATUSES)}"
            )
        if pattern_id not in self._data["patterns"]:
            raise KeyError(f"Pattern '{pattern_id}' not found in registry.")

        pattern = self._data["patterns"][pattern_id]
        old_status = pattern["review_status"]
        pattern["review_status"] = status
        pattern["review_history"].append({
            "timestamp": _utc_now(),
            "reviewer": reviewer,
            "old_status": old_status,
            "new_status": status,
            "rationale": rationale,
        })

        self._audit(
            "review",
            f"Pattern '{pattern_id}': {old_status} → {status} by {reviewer}",
        )
        self.save()
        return pattern

    # ─────────────────────────────────────────────────────────────────────────
    # QUERIES
    # ─────────────────────────────────────────────────────────────────────────

    def list_patterns(
        self,
        status_filter: str | None = None,
        sort_by: str = "novelty_score",
        descending: bool = True,
    ) -> list[dict[str, Any]]:
        """
        List all patterns (optionally filtered by review status).

        Parameters
        ----------
        status_filter : if provided, only patterns with this status are returned.
        sort_by : field to sort by ('novelty_score' | 'n_examples' | 'import_timestamp').
        descending : sort order.
        """
        patterns = list(self._data["patterns"].values())
        if status_filter:
            patterns = [p for p in patterns if p["review_status"] == status_filter]
        try:
            patterns.sort(key=lambda p: p.get(sort_by, 0), reverse=descending)
        except TypeError:
            pass
        return patterns

    def get_pattern(self, pattern_id: str) -> dict[str, Any] | None:
        return self._data["patterns"].get(pattern_id)

    def stats(self) -> dict[str, Any]:
        patterns = list(self._data["patterns"].values())
        status_counts: dict[str, int] = {}
        for p in patterns:
            s = p.get("review_status", "pending")
            status_counts[s] = status_counts.get(s, 0) + 1
        return {
            "total_patterns": len(patterns),
            "status_counts": status_counts,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # AUDIT
    # ─────────────────────────────────────────────────────────────────────────

    def _audit(self, action: str, detail: str) -> None:
        self._data["audit_log"].append({
            "timestamp": _utc_now(),
            "action": action,
            "detail": detail,
        })

    def audit_log(self) -> list[dict[str, Any]]:
        return list(self._data["audit_log"])


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def load_registry(registry_path: str | Path | None = None) -> PatternRegistry:
    """Convenience factory."""
    return PatternRegistry(registry_path)
