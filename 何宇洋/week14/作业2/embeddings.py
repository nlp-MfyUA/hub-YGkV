from threading import Lock

import numpy as np

from settings import EMBEDDING_MODEL

_lock = Lock()
_model = None


def encode(texts):
    global _model
    with _lock:
        if _model is None:
            from sentence_transformers import SentenceTransformer

            _model = SentenceTransformer(EMBEDDING_MODEL, device="cpu")
        vectors = _model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vectors, dtype="<f4")
