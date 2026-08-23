import numpy as np

from app.services.embedding_service import (
    embed_texts
)

from app.services.vector_store import (
    create_index,
    search
)


PAGE_ID = "test-page"


chunks = [
    "Cricket is a bat and ball sport.",
    "A cricket pitch is 22 yards long.",
    "Test cricket can be played over five days.",
    "T20 cricket consists of twenty overs per side."
]


print("Creating embeddings...")

embeddings = embed_texts(
    chunks
)

print(
    "Embedding shape:",
    embeddings.shape
)


print("Creating FAISS index...")

create_index(
    PAGE_ID,
    embeddings,
    chunks
)


print("Searching...")

query =embed_texts([
        "How long is a cricket pitch?"
    ])[0]


results =search(
        PAGE_ID,
        query,
        top_k=2
    )


print()
print(
    "RESULTS"
)
print(
    "======="
)


for result in results:

    print(
        f"Score: {result['score']:.4f}"
    )

    print(
        result["chunk"]
    )

    print()