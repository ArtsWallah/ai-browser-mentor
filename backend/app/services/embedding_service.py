from fastembed import TextEmbedding
import numpy as np

from app.services.memory_diagnostics import log_memory_checkpoint


MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

_model = None


def get_model():
    global _model

    if _model is None:
        log_memory_checkpoint("hf_model_download_check_begin")
        log_memory_checkpoint("sentence_transformer_init_begin")
        _model = TextEmbedding(
            model_name=MODEL_NAME
        )
        log_memory_checkpoint("sentence_transformer_init_complete")

    return _model


def embed_text(text: str) -> np.ndarray:
    model = get_model()

    log_memory_checkpoint("embedding_generation_begin")
    embeddings = list(
        model.embed([text])
    )
    log_memory_checkpoint("embedding_generation_complete")

    return np.asarray(
        embeddings[0],
        dtype=np.float32
    )


def embed_texts(texts: list[str]) -> np.ndarray:
    model = get_model()

    log_memory_checkpoint("embedding_generation_begin")
    embeddings = list(
        model.embed(texts)
    )
    log_memory_checkpoint("embedding_generation_complete")

    return np.asarray(
        embeddings,
        dtype=np.float32
    )
