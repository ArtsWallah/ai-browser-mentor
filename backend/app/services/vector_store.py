import os
import json
import faiss
import numpy as np


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

def get_index_path(page_id: str) -> str:

    safe_id = str(page_id).replace(
        "/",
        "_"
    ).replace(
        "\\",
        "_"
    ).replace(
        ":",
        "_"
    )

    return os.path.join(
        VECTOR_DIR,
        f"{safe_id}.index"
    )


def get_metadata_path(page_id: str) -> str:

    safe_id = str(page_id).replace(
        "/",
        "_"
    ).replace(
        "\\",
        "_"
    ).replace(
        ":",
        "_"
    )

    return os.path.join(
        VECTOR_DIR,
        f"{safe_id}.json"
    )


# ============================================================
# CREATE / SAVE INDEX
# ============================================================

def create_index(
    page_id: str,
    embeddings: np.ndarray,
    chunks: list
):

    embeddings = np.asarray(
    embeddings,
    dtype="float32"
)


    if embeddings.ndim == 1:
        embeddings = embeddings.reshape(1,-1)
            


    if embeddings.shape[1] != EMBEDDING_DIMENSION:

        raise ValueError(
            f"Expected embedding dimension "
            f"{EMBEDDING_DIMENSION}, "
            f"got {embeddings.shape[1]}"
        )


    # Inner product works as cosine similarity
    # because embeddings are normalized.
    index =faiss.IndexFlatIP(
            EMBEDDING_DIMENSION
        )


    index.add(
        embeddings
    )


    faiss.write_index(
        index,
        get_index_path(page_id)
    )


    metadata = {

        "page_id":
            page_id,

        "chunks":
            chunks
    }


    with open(
        get_metadata_path(page_id),
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            metadata,
            f,
            ensure_ascii=False,
            indent=2
        )


    return {
        "page_id":
            page_id,

        "count":
            len(chunks)
    }


# ============================================================
# LOAD INDEX
# ============================================================

def load_index(page_id: str):

    index_path =get_index_path(page_id)

    metadata_path = get_metadata_path(page_id)


    if not os.path.exists(
        index_path
    ):
        return None


    if not os.path.exists(
        metadata_path
    ):
        return None


    index =faiss.read_index(
            index_path
        )


    with open(
        metadata_path,
        "r",
        encoding="utf-8"
    ) as f:

        metadata = json.load(f)


    return {
        "index":
            index,

        "chunks":
            metadata.get(
                "chunks",
                []
            )
    }


# ============================================================
# SEARCH
# ============================================================

def search(
    page_id: str,
    query_embedding: np.ndarray,
    top_k: int = 5
):

    data =load_index(
            page_id
        )


    if data is None:
        return []


    query_embedding =np.asarray(
            query_embedding,
            dtype="float32"
        )


    if query_embedding.ndim == 1:

        query_embedding =query_embedding.reshape(
                1,
                -1
            )


    scores, indices =data["index"].search(
            query_embedding,
            min(
                top_k,
                data["index"].ntotal
            )
        )


    results = []


    chunks = data["chunks"]


    for score, idx in zip(
        scores[0],
        indices[0]
    ):

        if idx < 0:
            continue


        if idx >= len(chunks):
            continue


        results.append({

            "score":
                float(score),

            "chunk":
                chunks[idx]
        })


    return results