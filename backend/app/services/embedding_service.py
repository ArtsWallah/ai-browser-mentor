from sentence_transformers import SentenceTransformer
import numpy as np


MODEL_NAME = "all-MiniLM-L6-v2"

_model = None


def get_model():
    global _model

    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)

    return _model


def embed_text(text: str) -> np.ndarray:
    model = get_model()

    vector = model.encode(
        text,
        normalize_embeddings=True
    )

    return np.asarray(
        vector,
        dtype="float32"
    )


def embed_texts(texts: list[str]) -> np.ndarray:
    model = get_model()

    vectors = model.encode(
        texts,
        normalize_embeddings=True
    )

    return np.asarray(
        vectors,
        dtype="float32"
    )