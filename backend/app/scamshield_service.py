import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
from dotenv import load_dotenv

# Explicitly load the backend .env, regardless of the working directory.
BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(BACKEND_ENV, override=False)


def resolve_model_path(model_path: str | Path | None = None) -> Path:
    """Resolve model path against absolute, backend root, or current working directory."""
    if not model_path:
        model_path = os.getenv("SCAMSHIELD_MODEL_PATH")
    if not model_path:
        raise RuntimeError("SCAMSHIELD_MODEL_PATH is not configured.")

    raw_path = Path(model_path).expanduser()
    if raw_path.is_file():
        return raw_path

    backend_dir = Path(__file__).resolve().parents[1]
    candidate = (backend_dir / raw_path).resolve()
    if candidate.is_file():
        return candidate

    candidate_cwd = (Path.cwd() / raw_path).resolve()
    if candidate_cwd.is_file():
        return candidate_cwd

    return candidate


@lru_cache(maxsize=1)
def load_model() -> dict[str, Any]:
    """Load and validate the ScamShield multi-tactic model artifact."""
    model_path = os.getenv("SCAMSHIELD_MODEL_PATH")

    if not model_path:
        raise RuntimeError("SCAMSHIELD_MODEL_PATH is not configured.")

    path = resolve_model_path(model_path)

    if not path.is_file():
        raise RuntimeError(f"ScamShield model file was not found at {model_path}.")

    from app.services.model_integrity import verify_model_artifact
    verify_model_artifact(path)

    model = joblib.load(path)

    if not isinstance(model, dict):
        raise RuntimeError("Unsupported ScamShield model format.")

    if model.get("model_type") != "per_tactic_binary_v1":
        raise RuntimeError("Unsupported ScamShield model version.")

    return model


def find_defensible_spans(
    message: str,
    positive_features: list[dict[str, Any]],
    max_spans: int = 4
) -> list[dict[str, Any]]:
    """
    Locates exact, non-overlapping character spans in the raw message corresponding
    to n-grams that provided a positive contribution to the tactic log-odds.
    
    GUARANTEE: Does not fabricate spans. Only positive contributing features
    present in the input text with verified offsets are returned.
    """
    if not message or not positive_features:
        return []

    spans: list[dict[str, Any]] = []
    occupied_intervals: list[tuple[int, int]] = []

    for feat in positive_features:
        term = feat["feature"]
        words = term.split()
        # Allow whitespace or punctuation delimiters between words in multi-word n-grams
        pattern = r"\b" + r"[\s\W_]+".join(re.escape(w) for w in words) + r"\b"

        try:
            for match in re.finditer(pattern, message, flags=re.IGNORECASE):
                start, end = match.start(), match.end()

                # Guard against overlaps with existing evidence spans
                overlaps = any(start < o_end and end > o_start for o_start, o_end in occupied_intervals)
                if not overlaps:
                    occupied_intervals.append((start, end))
                    span_text = message[start:end]

                    # Verification check: slice must exactly match extracted text
                    if message[start:end] == span_text:
                        spans.append({
                            "text": span_text,
                            "start": start,
                            "end": end,
                            "feature": term,
                            "weight": feat["weight"],
                            "contribution": feat["contribution"]
                        })
                        break

                if len(spans) >= max_spans:
                    break
        except Exception:
            continue

        if len(spans) >= max_spans:
            break

    # Sort spans chronologically by appearance in text
    spans.sort(key=lambda s: s["start"])
    return spans


def explain_tactic_prediction(
    classifier: Any,
    message: str,
    tactic: str,
    threshold: float = 0.5,
    max_spans: int = 4
) -> dict[str, Any]:
    """
    Computes exact linear feature attribution (additive logit decomposition)
    for a TF-IDF + LogisticRegression binary tactic classifier.
    
    Logit = intercept + sum(weight_k * tfidf_k).
    Probability = sigmoid(logit).
    """
    # 1. Check classifier readiness
    if classifier is None:
        return {
            "tactic": tactic,
            "available": False,
            "detected": None,
            "score": None,
            "threshold": None,
            "evidence_spans": [],
            "top_features": [],
            "explanation": f"Classifier for tactic '{tactic}' is unavailable in the model artifact.",
            "explanation_method": "unavailable",
            "uncertainty_note": "Tactic model missing or unconfigured."
        }

    classes = list(getattr(classifier, "classes_", []))
    if 1 not in classes:
        return {
            "tactic": tactic,
            "available": False,
            "detected": None,
            "score": None,
            "threshold": None,
            "evidence_spans": [],
            "top_features": [],
            "explanation": f"Classifier for tactic '{tactic}' lacks trained positive class.",
            "explanation_method": "unavailable",
            "uncertainty_note": "Model classes do not support binary detection."
        }

    # 2. Extract probabilities and decision outcome
    probabilities = classifier.predict_proba([message])[0]
    score = float(probabilities[classes.index(1)])
    detected = bool(score >= threshold)

    # 3. Inspect TF-IDF and Linear weights
    try:
        tfidf = classifier.named_steps["tfidf"]
        clf = classifier.named_steps["classifier"]
        feature_names = tfidf.get_feature_names_out()
        coefs = clf.coef_[0]
        intercept = float(clf.intercept_[0])

        X = tfidf.transform([message])
        nonzero_cols = X.nonzero()[1]

        positive_features: list[dict[str, Any]] = []
        for col_idx in nonzero_cols:
            w = float(coefs[col_idx])
            val = float(X[0, col_idx])
            contrib = w * val
            if w > 0 and contrib > 0.001:
                positive_features.append({
                    "feature": feature_names[col_idx],
                    "weight": round(w, 4),
                    "contribution": round(contrib, 4),
                    "tfidf_value": round(val, 4)
                })

        # Rank positive features by additive log-odds contribution
        positive_features.sort(key=lambda f: f["contribution"], reverse=True)

        # 4. Extract evidence spans grounded in message text
        evidence_spans = find_defensible_spans(message, positive_features, max_spans=max_spans)

        # 5. Build defensible, concise explanation
        if detected:
            if evidence_spans:
                span_summaries = [f"'{s['text']}' (+{s['contribution']:.3f})" for s in evidence_spans[:3]]
                explanation = (
                    f"Tactic '{tactic}' detected (score {score:.2f} >= threshold {threshold:.2f}). "
                    f"Top positive indicator terms: {', '.join(span_summaries)}."
                )
            else:
                explanation = (
                    f"Tactic '{tactic}' detected (score {score:.2f} >= threshold {threshold:.2f}) "
                    f"primarily driven by baseline model bias (intercept {intercept:+.2f}) without individual dominant n-gram matches."
                )
        else:
            if positive_features:
                top_term = positive_features[0]
                explanation = (
                    f"Tactic '{tactic}' not detected (score {score:.2f} < threshold {threshold:.2f}). "
                    f"Terms like '{top_term['feature']}' (+{top_term['contribution']:.3f}) were present, but insufficient to cross detection threshold."
                )
            else:
                explanation = (
                    f"Tactic '{tactic}' not detected (score {score:.2f} < threshold {threshold:.2f}). "
                    "No positive contributing indicator n-grams were found in the text."
                )

        explanation_method = "linear_feature_attribution"

    except Exception as e:
        # Graceful degradation if pipeline architecture differs
        positive_features = []
        evidence_spans = []
        explanation = f"Score {score:.2f} for '{tactic}'. Internal feature attribution failed: {e}."
        explanation_method = "fallback_probability_only"

    return {
        "tactic": tactic,
        "available": True,
        "detected": detected,
        "score": round(score, 4),
        "threshold": round(threshold, 4),
        "evidence_spans": evidence_spans,
        "top_features": positive_features[:5],
        "explanation": explanation,
        "explanation_method": explanation_method,
        "uncertainty_note": (
            "Model scores are uncalibrated experimental outputs for specific social-engineering tactics. "
            "They do not establish whether an entire message is genuine or fraudulent."
        )
    }


def analyze_message(message: str) -> dict[str, Any]:
    """
    Upgraded ScamShield AI message analyzer with explainable, evidence-grounded tactic detection.
    Preserves backward-compatible API structure while providing detailed feature attribution.
    """
    clean_msg = (message or "").strip()
    if not clean_msg:
        raise ValueError("Message cannot be blank.")

    model = load_model()
    results: list[dict[str, Any]] = []
    detected_tactics: list[str] = []

    for tactic in model["tactics"]:
        classifier = model["models"].get(tactic)
        threshold = float(model["thresholds"].get(tactic, 0.5))

        finding = explain_tactic_prediction(
            classifier=classifier,
            message=clean_msg,
            tactic=tactic,
            threshold=threshold
        )
        results.append(finding)

        if finding.get("detected"):
            detected_tactics.append(tactic)

    return {
        "success": True,
        "model": "scamshield-tfidf-multilabel",
        "experimental": True,
        "detected_tactics": detected_tactics,
        "results": results,
        "tactic_findings": results,
        "explanation_method": "linear_feature_attribution",
        "explanation_limitations": (
            "Evidence spans represent lexical n-gram correlations with trained social-engineering tactics. "
            "They are model feature attributions, not causal proof of malicious intent. "
            "Results must be reviewed alongside sender context, URLs, and headers."
        ),
        "calibrated_probability_note": (
            "Model scores reflect uncalibrated sigmoid outputs from class-balanced binary logistic regression, "
            "not real-world Bayesian fraud probabilities."
        ),
        "disclaimer": (
            "Experimental tactic predictions only. Scores are not calibrated "
            "fraud probabilities and do not establish whether a message is a scam."
        ),
    }
