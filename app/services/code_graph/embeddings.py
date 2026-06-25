"""Code symbol embeddings via fastembed (ONNX, CPU).

The default model is ``jinaai/jina-embeddings-v2-base-code`` (768-dim, 8192-token
context, tuned for source code). The backend is loaded lazily and cached: import
or model-load failures (e.g. a broken onnxruntime build) raise
:class:`EmbeddingUnavailable` so callers can degrade to lexical-only search
instead of crashing.
"""

from __future__ import annotations

from functools import lru_cache

from loguru import logger


class EmbeddingUnavailable(RuntimeError):
    """Raised when the embedding backend cannot be loaded or run."""


# Keep the embedding text bounded — symbol metadata, not whole bodies.
_MAX_DOC_CHARS = 600
_MAX_TEXT_CHARS = 1200


def node_embedding_text(
    *,
    kind: str,
    name: str,
    qualified_name: str,
    signature: str | None,
    docstring: str | None,
) -> str:
    """Build the compact text representation embedded for a symbol.

    Combines kind, qualified name, signature, and a clamped docstring so the
    vector captures *what the symbol is and does* without its full body.
    """
    parts = [f"{kind} {qualified_name}"]
    if name and name != qualified_name:
        parts.append(name)
    if signature:
        parts.append(signature)
    if docstring:
        doc = " ".join(docstring.split())
        parts.append(doc[:_MAX_DOC_CHARS])
    return "\n".join(parts)[:_MAX_TEXT_CHARS]


class CodeEmbedder:
    """Thin wrapper over a fastembed ``TextEmbedding`` model."""

    def __init__(self, model_name: str, dim: int) -> None:
        self.model_name = model_name
        self.dim = dim
        self._model = self._load(model_name)

    @staticmethod
    def _load(model_name: str) -> object:
        try:
            from fastembed import TextEmbedding
        except Exception as exc:  # ImportError, or onnxruntime DLL failure
            raise EmbeddingUnavailable(
                f"fastembed/onnxruntime unavailable: {exc}"
            ) from exc
        try:
            from pathlib import Path

            # Use bundled model in repo first, fall back to config dir
            repo_cache = Path(__file__).resolve().parents[3] / "models" / "embedding"
            if repo_cache.is_dir():
                cache_dir = str(repo_cache)
            else:
                from app.core.config import settings

                cache_dir = str(Path(settings.EVOFLUX_CONFIG_DIR) / "models")
            return TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        except Exception as exc:
            raise EmbeddingUnavailable(
                f"failed to load embedding model '{model_name}': {exc}"
            ) from exc

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts into ``dim``-length float vectors."""
        if not texts:
            return []
        try:
            vectors = list(self._model.embed(texts))  # type: ignore[attr-defined]
        except Exception as exc:
            raise EmbeddingUnavailable(f"embedding failed: {exc}") from exc
        return [v.tolist() if hasattr(v, "tolist") else list(v) for v in vectors]

    def embed_one(self, text: str) -> list[float]:
        result = self.embed([text])
        if not result:
            raise EmbeddingUnavailable("embedding produced no vector")
        return result[0]


@lru_cache(maxsize=4)
def get_embedder(model_name: str, dim: int) -> CodeEmbedder:
    """Return a cached embedder for ``model_name``.

    Raises :class:`EmbeddingUnavailable` if the backend cannot be loaded.
    """
    logger.info("code_graph embedder loading model={} dim={}", model_name, dim)
    return CodeEmbedder(model_name, dim)
