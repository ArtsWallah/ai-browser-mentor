from fastembed import TextEmbedding
import numpy as np


MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

_model = None


def get_model():
    global _model

    if _model is None:
        _model = TextEmbedding(
            model_name=MODEL_NAME
        )

    return _model


def embed_text(text: str) -> np.ndarray:
    model = get_model()

    embeddings = list(
        model.embed([text])
    )

    return np.asarray(
        embeddings[0],
        dtype=np.float32
    )