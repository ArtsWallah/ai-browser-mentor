import threading
from fastembed import TextEmbedding
import numpy as np

from app.services.memory_diagnostics import log_memory_checkpoint


MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384
DEFAULT_BATCH_SIZE = 16

_model = None
_model_lock = threading.Lock()


def get_model():
    global _model

    if _model is None:
        with _model_lock:
            if _model is None:
                log_memory_checkpoint("hf_model_download_check_begin")
                log_memory_checkpoint("sentence_transformer_init_begin")
                _model = TextEmbedding(
                    model_name=MODEL_NAME,
                    threads=1,
                    enable_cpu_mem_arena=False,
                )
                log_memory_checkpoint("sentence_transformer_init_complete")

    return _model


def embed_text(text: str) -> np.ndarray:
    model = get_model()

    log_memory_checkpoint("embedding_generation_begin")
    embeddings = list(
        model.embed([text], batch_size=1)
    )
    log_memory_checkpoint("embedding_generation_complete")

    return np.asarray(
        embeddings[0],
        dtype=np.float32
    )


def embed_texts(texts: list[str], batch_size: int = DEFAULT_BATCH_SIZE) -> np.ndarray:
    if not texts:
        return np.empty((0, EMBEDDING_DIMENSION), dtype=np.float32)

    model = get_model()

    log_memory_checkpoint("embedding_generation_begin")
    embeddings = list(
        model.embed(texts, batch_size=batch_size)
    )
    log_memory_checkpoint("embedding_generation_complete")

    return np.asarray(
        embeddings,
        dtype=np.float32
    )
