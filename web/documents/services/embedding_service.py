from sentence_transformers import SentenceTransformer
import logging

logger = logging.getLogger(__name__)


class EmbeddingService:

    _model_cache: dict = {}

    @classmethod
    def get_model(cls, model_name: str) -> SentenceTransformer:
        """Get or load embedding model (cached in memory after first load)."""
        if model_name not in cls._model_cache:
            logger.info(f"Loading embedding model: {model_name}")
            model = SentenceTransformer(model_name)
            cls._model_cache[model_name] = model
            logger.info(f"Model {model_name} loaded and cached")
        else:
            logger.debug(f"Using cached model: {model_name}")
        return cls._model_cache[model_name]

    @classmethod
    def embed_text(cls, text: str, model_name: str) -> list[float]:
        """Generate an embedding vector for a single text string."""
        if not text or not text.strip():
            raise ValueError("text must be a non-empty string")
        model = cls.get_model(model_name)
        return model.encode(text, convert_to_numpy=True).tolist()

    @classmethod
    def embed_batch(cls, texts: list[str], model_name: str) -> list[list[float]]:
        """Generate embedding vectors for a list of texts."""
        model = cls.get_model(model_name)
        embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        return [emb.tolist() for emb in embeddings]

    @classmethod
    def clear_cache(cls) -> None:
        """Evict all cached models from memory."""
        logger.info("Clearing embedding model cache")
        cls._model_cache.clear()

    @classmethod
    def get_cache_info(cls) -> dict:
        """Return info about currently cached models."""
        return {
            'cached_models': list(cls._model_cache.keys()),
            'cache_size': len(cls._model_cache),
        }
