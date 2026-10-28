import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "models" / "model_integrity_manifest.json"
)


class ModelIntegrityError(RuntimeError):
    """Raised when model artifact checksum verification fails or manifest is invalid."""
    pass


def compute_sha256(file_path: Path | str, chunk_size: int = 65536) -> str:
    """
    Compute the SHA-256 digest of a file incrementally in chunks.
    Avoids reading entire binary model weights into memory at once.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Model artifact not found at {path.name}")

    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def load_trusted_manifest(manifest_path: Path | str | None = None) -> dict[str, Any]:
    """
    Load and parse the committed trusted model integrity manifest.
    Fails safely by raising ModelIntegrityError if the file is missing or malformed.
    """
    if manifest_path is None:
        env_manifest = os.getenv("SCAMSHIELD_INTEGRITY_MANIFEST_PATH")
        path = Path(env_manifest).resolve() if env_manifest else DEFAULT_MANIFEST_PATH
    else:
        path = Path(manifest_path).resolve()

    if not path.is_file():
        raise ModelIntegrityError(
            f"Model integrity manifest not found at {path.name}. "
            "Cannot safely load unverified model artifacts without trusted hashes."
        )

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ModelIntegrityError(f"Model integrity manifest is malformed: {exc}") from exc

    if not isinstance(data, dict) or "models" not in data or not isinstance(data["models"], dict):
        raise ModelIntegrityError(
            "Model integrity manifest schema is invalid: missing 'models' dictionary."
        )

    return data


def verify_model_artifact(
    model_path: Path | str,
    manifest_path: Path | str | None = None,
    expected_sha256: str | None = None,
) -> bool:
    """
    Verify the SHA-256 checksum of a model file against an explicit expected hash
    or the committed integrity manifest.

    Security rules:
    - Never calculates a hash and automatically trusts it.
    - Constant-time comparison (hmac.compare_digest) to prevent timing leakage.
    - Fails safely by raising ModelIntegrityError on mismatch or missing record.
    - Never logs model contents or sensitive filesystem paths.
    """
    path = Path(model_path)
    if not path.is_file():
        raise FileNotFoundError(f"Model artifact not found: {path.name}")

    expected_hash: str | None = expected_sha256

    if not expected_hash:
        # Check environment variable overrides for external volume deployments
        if path.name == "baseline_tfidf_logistic.pkl":
            expected_hash = os.getenv("SCAMSHIELD_SPAM_MODEL_SHA256")
        elif path.name == "tfidf_multilabel_baseline.joblib":
            expected_hash = os.getenv("SCAMSHIELD_MODEL_SHA256")

    if not expected_hash:
        manifest = load_trusted_manifest(manifest_path)
        model_entry = manifest["models"].get(path.name)
        if not model_entry or not isinstance(model_entry, dict) or "sha256" not in model_entry:
            raise ModelIntegrityError(
                f"No trusted integrity record found for model artifact '{path.name}'. "
                "Refusing to load untrusted binary model without verified checksum."
            )
        expected_hash = str(model_entry["sha256"]).strip().lower()

    actual_hash = compute_sha256(path)

    if not hmac.compare_digest(actual_hash, expected_hash.strip().lower()):
        logger.warning(
            "Model integrity verification failure: SHA-256 digest mismatch for artifact '%s'.",
            path.name,
        )
        raise ModelIntegrityError(
            f"Integrity check failed for model '{path.name}'. "
            "Artifact binary digest does not match trusted checksum."
        )

    logger.debug("Model integrity verified successfully for artifact '%s'.", path.name)
    return True


def update_integrity_manifest(
    models_dir: Path | str | None = None,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """
    Explicitly recalculate and update the trusted manifest when models are
    intentionally retrained or replaced.
    Provides a reproducible, documented administrative path to update hashes.
    """
    base_dir = Path(models_dir).resolve() if models_dir else DEFAULT_MANIFEST_PATH.parent
    target_manifest = Path(output_path).resolve() if output_path else DEFAULT_MANIFEST_PATH

    models_data: dict[str, Any] = {}
    for ext in ("*.pkl", "*.joblib"):
        for model_file in sorted(base_dir.glob(ext)):
            sha = compute_sha256(model_file)
            size = model_file.stat().st_size
            fmt = "joblib" if model_file.suffix == ".joblib" else "joblib/pickle"
            models_data[model_file.name] = {
                "sha256": sha,
                "size_bytes": size,
                "format": fmt,
                "model_type": (
                    "per_tactic_binary_v1"
                    if "multilabel" in model_file.name
                    else "binary_logistic_regression"
                ),
            }

    manifest = {
        "$schema": "scamshield_model_integrity_v1",
        "description": (
            "Committed SHA-256 integrity manifest for ScamShield model artifacts. "
            "Do not modify manually unless models are intentionally retrained."
        ),
        "hash_algorithm": "sha256",
        "models": models_data,
    }

    target_manifest.parent.mkdir(parents=True, exist_ok=True)
    target_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    import sys
    if "--update" in sys.argv:
        updated = update_integrity_manifest()
        print(f"Updated integrity manifest with {len(updated['models'])} models.")
    else:
        print("Model Integrity Service: checking default manifest models...")
        m = load_trusted_manifest()
        for name, entry in m["models"].items():
            f = DEFAULT_MANIFEST_PATH.parent / name
            if f.is_file():
                verify_model_artifact(f)
                print(f"[OK] {name}: verified ({entry['sha256'][:16]}...)")
            else:
                print(f"[MISSING] {name}: file not found on disk")
