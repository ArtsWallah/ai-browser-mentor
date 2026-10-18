import os
from functools import lru_cache
from pathlib import Path

import joblib
from dotenv import load_dotenv

# Explicitly load the backend .env, regardless of the working directory.
BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(BACKEND_ENV, override=False)

@lru_cache(maxsize=1)
def load_model():
    model_path = os.getenv("SCAMSHIELD_MODEL_PATH")

    if not model_path:
        raise RuntimeError("SCAMSHIELD_MODEL_PATH is not configured.")

    path = Path(model_path).expanduser()
    if not path.is_file():
        raise RuntimeError("ScamShield model file was not found.")

    model = joblib.load(path)

    if not isinstance(model, dict):
        raise RuntimeError("Unsupported ScamShield model format.")

    if model.get("model_type") != "per_tactic_binary_v1":
        raise RuntimeError("Unsupported ScamShield model version.")

    return model


def analyze_message(message: str) -> dict:
    model = load_model()
    results = []
    detected_tactics = []

    for tactic in model["tactics"]:
        classifier = model["models"].get(tactic)

        if classifier is None or 1 not in list(classifier.classes_):
            results.append({
                "tactic": tactic,
                "available": False,
                "detected": None,
                "score": None,
            })
            continue

        classes = list(classifier.classes_)
        probabilities = classifier.predict_proba([message])[0]
        score = float(probabilities[classes.index(1)])
        threshold = float(model["thresholds"].get(tactic, 0.5))
        detected = score >= threshold

        results.append({
            "tactic": tactic,
            "available": True,
            "detected": detected,
            "score": round(score, 4),
        })

        if detected:
            detected_tactics.append(tactic)

    return {
        "success": True,
        "model": "scamshield-tfidf-multilabel",
        "experimental": True,
        "detected_tactics": detected_tactics,
        "results": results,
        "disclaimer": (
            "Experimental tactic predictions only. Scores are not calibrated "
            "fraud probabilities and do not establish whether a message is a scam."
        ),
    }
