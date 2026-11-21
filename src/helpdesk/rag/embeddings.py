"""Local embeddings via fastembed (ONNX, no second API vendor). Downloads the model on first use."""
from __future__ import annotations

from typing import Protocol

import numpy as np


class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[np.ndarray]: ...
    def embed_query(self, text: str) -> np.ndarray: ...


class FastEmbedEmbedder:
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        self._model_name = model_name
        self._model = None

    def _load(self):  # lazy: keeps imports and unit tests light
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self._model_name)
        return self._model

    def embed_documents(self, texts: list[str]) -> list[np.ndarray]:
        return [np.asarray(v, dtype=np.float32) for v in self._load().embed(texts)]

    def embed_query(self, text: str) -> np.ndarray:
        return np.asarray(next(iter(self._load().query_embed(text))), dtype=np.float32)
