"""Local embeddings for source chunks and user queries."""

from __future__ import annotations

import math
from typing import Any, Sequence


MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384


class EmbeddingModel:
    """Run the shared MiniLM model locally for both documents and queries."""

    def __init__(self, model_name: str = MODEL_NAME, model: Any | None = None):
        self.model_name = model_name
        if model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as error:
                raise RuntimeError(
                    "Install sentence-transformers to create local embeddings"
                ) from error
            model = SentenceTransformer(model_name, device="cpu")
        self._model = model

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Encode document texts into validated, normalized vectors."""
        return self._encode(texts)

    def embed_query(self, text: str) -> list[float]:
        """Encode one query using the same model and settings as documents."""
        return self._encode([text])[0]

    def _encode(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.encode(
            list(texts),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        if hasattr(vectors, "tolist"):
            vectors = vectors.tolist()
        normalized_vectors = [[float(value) for value in vector] for vector in vectors]
        if len(normalized_vectors) != len(texts):
            raise ValueError("Embedding model returned an unexpected number of vectors")
        for vector in normalized_vectors:
            if len(vector) != EMBEDDING_DIMENSION:
                raise ValueError(
                    f"Expected {EMBEDDING_DIMENSION}-dimensional embeddings; "
                    f"received {len(vector)} dimensions"
                )
            if not all(math.isfinite(value) for value in vector):
                raise ValueError("Embedding model returned a non-finite vector value")
        return normalized_vectors