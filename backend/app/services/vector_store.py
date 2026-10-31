import os
import json
import hashlib
import shutil
import numpy as np
from app.services.memory_diagnostics import log_memory_checkpoint

try:
    import faiss
    FAISS_AVAILABLE = True
except Exception:
    faiss = None
    FAISS_AVAILABLE = False


VECTOR_DIR = os.path.join(
    os.path.dirname(
        os.path.dirname(
            os.path.dirname(__file__)
        )
    ),
    "data",
    "vector_store"
)

os.makedirs(
    VECTOR_DIR,
    exist_ok=True
)

EMBEDDING_DIMENSION = 384


# ============================================================
# PATHS & SAFE IDENTIFIERS
# ============================================================

def _safe_id(page_id: str, session_hash: str | None = None) -> str:
    """
    Deterministic, collision-resistant, and filesystem-safe filename identifier.
    Transforms arbitrary page IDs (optionally scoped by session_hash) into a strictly validated
    64-character lowercase SHA-256 hex string.

    Guarantees:
    - Exactly 64 characters long, containing only lowercase hexadecimal characters [0-9a-f].
    - Multi-user isolation: when session_hash is provided, storage is strictly scoped to that session.
    - Immune to Windows reserved names (CON, PRN, AUX, NUL, COM1-9, LPT1-9).
    - Immune to illegal characters (* ? < > | " : / \\) and control/null bytes.
    - Immune to directory traversal (.. and .).
    - Rejects empty, whitespace-only, or None inputs safely with ValueError.
    - Deterministic: identical inputs always produce identical filenames.
    - Collision-resistant: different inputs produce different filenames.
    """
    if page_id is None:
        raise ValueError("page_id cannot be None")

    if not isinstance(page_id, (str, bytes)):
        page_id = str(page_id)

    if isinstance(page_id, bytes):
        raw_bytes = page_id
    else:
        clean = page_id.strip()
        if not clean:
            raise ValueError("page_id cannot be empty or whitespace-only")
        raw_bytes = clean.encode("utf-8")

    if session_hash is not None:
        if not isinstance(session_hash, str) or not session_hash.strip():
            raise ValueError("session_hash cannot be empty or whitespace-only")
        clean_sh = session_hash.strip().lower()
        if len(clean_sh) != 64 or not all(c in "0123456789abcdef" for c in clean_sh):
            raise ValueError("session_hash must be a valid 64-character lowercase hex digest")
        raw_bytes = f"{clean_sh}:".encode("utf-8") + raw_bytes

    digest = hashlib.sha256(raw_bytes).hexdigest().lower()
    return digest


def _resolve_safe_path(filename: str) -> str:
    """
    Validates vector-store path containment and verifies no symlink or traversal escape.
    """
    if not isinstance(filename, str) or not filename.endswith((".index", ".npy", ".json")):
        raise ValueError("Invalid vector store filename extension")

    base_name = filename.rsplit(".", 1)[0]
    if len(base_name) != 64 or not all(c in "0123456789abcdef" for c in base_name):
        raise ValueError("Invalid vector store filename base format")

    abs_vector_dir = os.path.abspath(VECTOR_DIR)
    target_path = os.path.abspath(os.path.join(VECTOR_DIR, filename))

    # Path traversal safety check
    if not target_path.startswith(abs_vector_dir + os.sep) and target_path != abs_vector_dir:
        raise ValueError("Path traversal detected outside vector store directory")

    # Symlink safety check: reject symlinks
    if os.path.islink(target_path):
        raise ValueError("Symlink traversal detected in vector store path")

    return target_path


def _legacy_safe_id(page_id: str) -> str | None:
    """Legacy unhashed sanitization mapping for backward compatibility."""
    if page_id is None:
        return None
    clean = str(page_id).strip()
    if not clean:
        return None
    return clean.replace("/", "_").replace("\\", "_").replace(":", "_")


def _get_legacy_index_path(page_id: str) -> str | None:
    lid = _legacy_safe_id(page_id)
    return os.path.join(VECTOR_DIR, f"{lid}.index") if lid else None


def _get_legacy_embeddings_path(page_id: str) -> str | None:
    lid = _legacy_safe_id(page_id)
    return os.path.join(VECTOR_DIR, f"{lid}.npy") if lid else None


def _get_legacy_metadata_path(page_id: str) -> str | None:
    lid = _legacy_safe_id(page_id)
    return os.path.join(VECTOR_DIR, f"{lid}.json") if lid else None


def get_index_path(page_id: str, session_hash: str | None = None) -> str:
    filename = f"{_safe_id(page_id, session_hash)}.index"
    return _resolve_safe_path(filename)


def get_embeddings_path(page_id: str, session_hash: str | None = None) -> str:
    filename = f"{_safe_id(page_id, session_hash)}.npy"
    return _resolve_safe_path(filename)


def get_metadata_path(page_id: str, session_hash: str | None = None) -> str:
    filename = f"{_safe_id(page_id, session_hash)}.json"
    return _resolve_safe_path(filename)


def migrate_legacy_index(page_id: str) -> bool:
    """
    Transparently migrates an existing unhashed legacy index file
    to its new hardened SHA-256 path, ensuring no disruption to stored data.
    """
    if not page_id or not str(page_id).strip():
        return False
    try:
        target_meta = get_metadata_path(page_id)
        target_idx = get_index_path(page_id)
        target_npy = get_embeddings_path(page_id)
    except ValueError:
        return False

    legacy_meta = _get_legacy_metadata_path(page_id)
    if not legacy_meta or not os.path.exists(legacy_meta):
        return False

    migrated = False
    try:
        if not os.path.exists(target_meta):
            shutil.copy2(legacy_meta, target_meta)
            migrated = True

        legacy_idx = _get_legacy_index_path(page_id)
        if legacy_idx and os.path.exists(legacy_idx) and not os.path.exists(target_idx):
            shutil.copy2(legacy_idx, target_idx)
            migrated = True

        legacy_npy = _get_legacy_embeddings_path(page_id)
        if legacy_npy and os.path.exists(legacy_npy) and not os.path.exists(target_npy):
            shutil.copy2(legacy_npy, target_npy)
            migrated = True

        return migrated
    except OSError:
        return False


# ============================================================
# CREATE / SAVE INDEX
# ============================================================

def create_index(
    page_id: str,
    embeddings: np.ndarray,
    chunks: list,
    session_hash: str | None = None,
):
    if not page_id or not str(page_id).strip():
        raise ValueError("page_id cannot be empty or blank")

    embeddings = np.asarray(embeddings, dtype="float32")

    if embeddings.ndim == 1:
        embeddings = embeddings.reshape(1, -1)

    if embeddings.shape[1] != EMBEDDING_DIMENSION:
        raise ValueError(
            f"Expected embedding dimension {EMBEDDING_DIMENSION}, got {embeddings.shape[1]}"
        )

    log_memory_checkpoint("faiss_index_create_begin")

    # Always persist numpy embeddings for universal portability / fallback
    np.save(get_embeddings_path(page_id, session_hash), embeddings)

    # If FAISS is available, also build and save the FAISS index
    if FAISS_AVAILABLE and faiss is not None:
        try:
            index = faiss.IndexFlatIP(EMBEDDING_DIMENSION)
            index.add(embeddings)
            faiss.write_index(index, get_index_path(page_id, session_hash))
        except Exception as error:
            print(f"[vector_store] FAISS index creation failed, using numpy store: {error}")

    metadata = {
        "page_id": page_id,
        "session_hash": session_hash,
        "chunks": chunks
    }

    with open(get_metadata_path(page_id, session_hash), "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    log_memory_checkpoint("faiss_index_create_complete")

    return {
        "page_id": page_id,
        "count": len(chunks)
    }


# ============================================================
# LOAD INDEX & METADATA
# ============================================================

def get_metadata(page_id: str, session_hash: str | None = None) -> dict | None:
    """Safely retrieve only the metadata/chunks for a page without loading full vectors."""
    if not page_id or not str(page_id).strip():
        return None
    try:
        path = get_metadata_path(page_id, session_hash)
    except ValueError:
        return None

    if not os.path.exists(path):
        # Legacy fallback permitted ONLY when session_hash is None (never adopt unowned legacy for a session)
        if session_hash is None:
            legacy_path = _get_legacy_metadata_path(page_id)
            if legacy_path and os.path.exists(legacy_path):
                path = legacy_path
            else:
                return None
        else:
            return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_index(page_id: str, session_hash: str | None = None):
    if not page_id or not str(page_id).strip():
        return None

    try:
        metadata_path = get_metadata_path(page_id, session_hash)
    except ValueError:
        return None

    # Check primary hardened path
    if not os.path.exists(metadata_path):
        # Legacy fallback permitted ONLY when session_hash is None (never adopt unowned legacy for a session)
        if session_hash is None:
            legacy_path = _get_legacy_metadata_path(page_id)
            if legacy_path and os.path.exists(legacy_path):
                # Transparently migrate legacy files
                migrate_legacy_index(page_id)
                if not os.path.exists(metadata_path):
                    metadata_path = legacy_path
                    index_path = _get_legacy_index_path(page_id)
                    npy_path = _get_legacy_embeddings_path(page_id)
                else:
                    index_path = get_index_path(page_id)
                    npy_path = get_embeddings_path(page_id)
            else:
                return None
        else:
            return None
    else:
        index_path = get_index_path(page_id, session_hash)
        npy_path = get_embeddings_path(page_id, session_hash)

    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
    except Exception:
        return None

    chunks = metadata.get("chunks", [])

    # Try loading FAISS index first if available
    if FAISS_AVAILABLE and faiss is not None and index_path and os.path.exists(index_path):
        try:
            index = faiss.read_index(index_path)
            return {
                "type": "faiss",
                "index": index,
                "chunks": chunks
            }
        except Exception:
            pass

    # Fallback to numpy embeddings
    if npy_path and os.path.exists(npy_path):
        try:
            embeddings = np.load(npy_path)
            return {
                "type": "numpy",
                "embeddings": embeddings,
                "chunks": chunks
            }
        except Exception:
            pass

    return None


def delete_index(page_id: str, session_hash: str | None = None) -> bool:
    """
    Safely delete all stored files (.index, .npy, .json) for a given page_id and session_hash.
    Returns True if at least one file was removed, False otherwise.
    """
    if not page_id or not str(page_id).strip():
        return False

    removed = False

    # Target hardened SHA-256 paths
    try:
        paths = [
            get_index_path(page_id, session_hash),
            get_embeddings_path(page_id, session_hash),
            get_metadata_path(page_id, session_hash)
        ]
        for p in paths:
            if os.path.exists(p) and not os.path.islink(p):
                try:
                    os.remove(p)
                    removed = True
                except OSError:
                    pass
    except ValueError:
        pass

    # Target legacy paths if present and session_hash is None
    if session_hash is None:
        legacy_id = _legacy_safe_id(page_id)
        if legacy_id:
            legacy_paths = [
                os.path.join(VECTOR_DIR, f"{legacy_id}.index"),
                os.path.join(VECTOR_DIR, f"{legacy_id}.npy"),
                os.path.join(VECTOR_DIR, f"{legacy_id}.json"),
            ]
            for p in legacy_paths:
                if os.path.exists(p) and not os.path.islink(p):
                    try:
                        os.remove(p)
                        removed = True
                    except OSError:
                        pass

    return removed


# ============================================================
# SEARCH
# ============================================================

def search(
    page_id: str,
    query_embedding: np.ndarray,
    top_k: int = 5,
    session_hash: str | None = None,
):
    data = load_index(page_id, session_hash=session_hash)
    if data is None:
        return []

    query_embedding = np.asarray(query_embedding, dtype="float32")
    if query_embedding.ndim == 1:
        query_embedding = query_embedding.reshape(1, -1)

    chunks = data.get("chunks", [])
    if not chunks:
        return []

    # FAISS search branch
    if data.get("type") == "faiss":
        index = data["index"]
        scores, indices = index.search(
            query_embedding,
            min(top_k, index.ntotal)
        )
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if 0 <= idx < len(chunks):
                results.append({
                    "score": float(score),
                    "chunk": chunks[idx]
                })
        return results

    # Pure NumPy cosine similarity branch
    embeddings = data.get("embeddings")
    if embeddings is None or len(embeddings) == 0:
        return []

    # Normalize vectors for accurate cosine similarity
    query_norm = np.linalg.norm(query_embedding)
    if query_norm > 0:
        query_vec = query_embedding / query_norm
    else:
        query_vec = query_embedding

    doc_norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    doc_norms[doc_norms == 0] = 1.0
    norm_embeddings = embeddings / doc_norms

    sims = np.dot(norm_embeddings, query_vec.T).squeeze()
    if np.ndim(sims) == 0:
        sims = np.array([sims])

    ranked_indices = np.argsort(-sims)[:min(top_k, len(chunks))]

    results = []
    for idx in ranked_indices:
        if 0 <= idx < len(chunks):
            results.append({
                "score": float(sims[idx]),
                "chunk": chunks[idx]
            })

    return results


def init_vector_store_dir(base_dir=None) -> str:
    """Safely initialize vector store directory on startup."""
    target_dir = str(base_dir) if base_dir is not None else VECTOR_DIR
    os.makedirs(target_dir, exist_ok=True)
    return target_dir


def cleanup_temporary_vector_store(max_age_hours: int = 24, base_dir=None) -> int:
    """
    Safely purges stale temporary vector-store index files (.index, .npy, .json)
    older than max_age_hours to prevent unbounded disk growth.

    SAFETY GUARANTEES:
    - Only operates strictly inside the isolated target directory.
    - NEVER touches dataset, model, or registry files in parent directories.
    - Gracefully handles locked files.

    Returns:
        Number of removed temporary files.
    """
    import time
    target_dir = str(base_dir) if base_dir is not None else VECTOR_DIR
    if not os.path.isdir(target_dir):
        return 0

    now = time.time()
    cutoff = now - (max_age_hours * 3600)
    removed_count = 0

    try:
        entries = os.listdir(target_dir)
    except OSError:
        return 0

    for fname in entries:
        # Strictly target temporary vector store extensions only
        if not (fname.endswith(".index") or fname.endswith(".npy") or fname.endswith(".json") or fname.endswith(".faiss")):
            continue
        fpath = os.path.join(target_dir, fname)
        try:
            if os.path.isfile(fpath):
                mtime = os.path.getmtime(fpath)
                if mtime < cutoff:
                    os.remove(fpath)
                    removed_count += 1
        except OSError:
            pass

    return removed_count