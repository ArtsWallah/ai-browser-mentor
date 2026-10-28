import os
import json
import numpy as np

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
# PATHS
# ============================================================

def _safe_id(page_id: str) -> str:
    return str(page_id).replace("/", "_").replace("\\", "_").replace(":", "_")


def get_index_path(page_id: str) -> str:
    return os.path.join(VECTOR_DIR, f"{_safe_id(page_id)}.index")


def get_embeddings_path(page_id: str) -> str:
    return os.path.join(VECTOR_DIR, f"{_safe_id(page_id)}.npy")


def get_metadata_path(page_id: str) -> str:
    return os.path.join(VECTOR_DIR, f"{_safe_id(page_id)}.json")


# ============================================================
# CREATE / SAVE INDEX
# ============================================================

def create_index(
    page_id: str,
    embeddings: np.ndarray,
    chunks: list
):
    embeddings = np.asarray(embeddings, dtype="float32")

    if embeddings.ndim == 1:
        embeddings = embeddings.reshape(1, -1)

    if embeddings.shape[1] != EMBEDDING_DIMENSION:
        raise ValueError(
            f"Expected embedding dimension {EMBEDDING_DIMENSION}, got {embeddings.shape[1]}"
        )

    # Always persist numpy embeddings for universal portability / fallback
    np.save(get_embeddings_path(page_id), embeddings)

    # If FAISS is available, also build and save the FAISS index
    if FAISS_AVAILABLE and faiss is not None:
        try:
            index = faiss.IndexFlatIP(EMBEDDING_DIMENSION)
            index.add(embeddings)
            faiss.write_index(index, get_index_path(page_id))
        except Exception as error:
            print(f"[vector_store] FAISS index creation failed, using numpy store: {error}")

    metadata = {
        "page_id": page_id,
        "chunks": chunks
    }

    with open(get_metadata_path(page_id), "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    return {
        "page_id": page_id,
        "count": len(chunks)
    }


# ============================================================
# LOAD INDEX
# ============================================================

def load_index(page_id: str):
    metadata_path = get_metadata_path(page_id)
    if not os.path.exists(metadata_path):
        return None

    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
    except Exception:
        return None

    chunks = metadata.get("chunks", [])

    # Try loading FAISS index first if available
    index_path = get_index_path(page_id)
    if FAISS_AVAILABLE and faiss is not None and os.path.exists(index_path):
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
    npy_path = get_embeddings_path(page_id)
    if os.path.exists(npy_path):
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


# ============================================================
# SEARCH
# ============================================================

def search(
    page_id: str,
    query_embedding: np.ndarray,
    top_k: int = 5
):
    data = load_index(page_id)
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