import faiss
import numpy as np


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

        # Inner Product + normalized vectors
        # gives us cosine similarity.
        self.index = faiss.IndexFlatIP(
            dimension
        )

        # Metadata corresponding to each
        # vector stored in FAISS.
        self.documents = []


    # ========================================================
    # ADD DOCUMENT
    # ========================================================

    def add(
        self,
        embedding: list[float],
        document: dict
    ):

        normalized = normalize_embedding(
            embedding
        )

        vector = np.array(
            [normalized],
            dtype="float32"
        )

        self.index.add(
            vector
        )

        self.documents.append(
            document
        )


    # ========================================================
    # SEARCH
    # ========================================================

    def search(
        self,
        embedding: list[float],
        top_k: int = 5,
        page_id: str | None = None
    ):

        if self.index.ntotal == 0:

            return []


        normalized = normalize_embedding(
            embedding
        )

        query_vector = np.array(
            [normalized],
            dtype="float32"
        )


        # ----------------------------------------------------
        # Search more candidates than we finally need.
        #
        # This is important because we may need to remove
        # chunks belonging to other pages.
        # ----------------------------------------------------

        search_k = min(
            max(
                top_k * 10,
                top_k
            ),
            self.index.ntotal
        )


        scores, indices = self.index.search(
            query_vector,
            search_k
        )


        results = []


        for score, index in zip(
            scores[0],
            indices[0]
        ):

            if index == -1:
                continue


            document = self.documents[
                index
            ]


            # ------------------------------------------------
            # PAGE FILTER
            # ------------------------------------------------

            if page_id is not None:

                if document.get(
                    "page_id"
                ) != page_id:

                    continue


            results.append({

                "score":
                    float(score),

                "document":
                    document
            })


            # Stop once we have enough
            # results for the requested page.
            if len(results) >= top_k:

                break


        return results


    # ========================================================
    # COUNT
    # ========================================================

    def count(self) -> int:

        return self.index.ntotal


    # ========================================================
    # CLEAR
    # ========================================================

    def clear(self):

        self.index = faiss.IndexFlatIP(
            self.dimension
        )

        self.documents = []