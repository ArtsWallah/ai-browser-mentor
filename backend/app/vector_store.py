import numpy as np

try:
    import faiss
    FAISS_AVAILABLE = True
except Exception:
    faiss = None
    FAISS_AVAILABLE = False


# ============================================================
# EMBEDDING NORMALIZATION
# ============================================================

def normalize_embedding(
    embedding: list[float]
) -> list[float]:
    vector = np.array(
        embedding,
        dtype="float32"
    )

    norm = np.linalg.norm(vector)
    if norm == 0:
        return embedding

    normalized = vector / norm
    return normalized.tolist()


# ============================================================
# VECTOR STORE
# ============================================================

class VectorStore:

    def __init__(
        self,
        dimension: int
    ):
        self.dimension = dimension
        self.documents = []
        self._vectors = []

        if FAISS_AVAILABLE and faiss is not None:
            try:
                self.index = faiss.IndexFlatIP(dimension)
            except Exception:
                self.index = None
        else:
            self.index = None

    # ========================================================
    # ADD DOCUMENT
    # ========================================================

    def add(
        self,
        embedding: list[float],
        document: dict
    ):
        normalized = normalize_embedding(embedding)
        self._vectors.append(normalized)
        self.documents.append(document)

        if self.index is not None:
            try:
                vector = np.array([normalized], dtype="float32")
                self.index.add(vector)
            except Exception:
                pass

    # ========================================================
    # SEARCH
    # ========================================================

    def search(
        self,
        embedding: list[float],
        top_k: int = 5,
        page_id: str | None = None
    ):
        if not self.documents:
            return []

        normalized = normalize_embedding(embedding)

        if self.index is not None:
            try:
                query_vector = np.array([normalized], dtype="float32")
                search_k = min(max(top_k * 10, top_k), self.index.ntotal)
                scores, indices = self.index.search(query_vector, search_k)

                results = []
                for score, index in zip(scores[0], indices[0]):
                    if index == -1 or index >= len(self.documents):
                        continue
                    doc = self.documents[index]
                    if page_id is not None and doc.get("page_id") != page_id:
                        continue
                    results.append({
                        "score": float(score),
                        "document": doc
                    })
                    if len(results) >= top_k:
                        break
                return results
            except Exception:
                pass

        # NumPy fallback
        query_vec = np.array(normalized, dtype="float32")
        vectors_arr = np.array(self._vectors, dtype="float32")
        scores = np.dot(vectors_arr, query_vec)

        ranked_indices = np.argsort(-scores)
        results = []
        for idx in ranked_indices:
            doc = self.documents[idx]
            if page_id is not None and doc.get("page_id") != page_id:
                continue
            results.append({
                "score": float(scores[idx]),
                "document": doc
            })
            if len(results) >= top_k:
                break
        return results

    # ========================================================
    # COUNT
    # ========================================================

    def count(self) -> int:
        return len(self.documents)

    # ========================================================
    # CLEAR
    # ========================================================

    def clear(self):
        self.documents = []
        self._vectors = []
        if FAISS_AVAILABLE and faiss is not None:
            try:
                self.index = faiss.IndexFlatIP(self.dimension)
            except Exception:
                self.index = None
        else:
            self.index = None