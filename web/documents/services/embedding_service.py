"""
Converts text into numbers (vectors) using AI models, and keeps models in memory for speed(caching). <<Real shit here>>
"""

from typing import List
from sentence_transformers import SentenceTransformer
import logging

logger = logging.getLogger(__name__)


class EmbeddingService:
    
    # Class-level cache - persists across all requests
    _model_cache: dict = {}
    
    @classmethod
    def get_model(cls, model_name: str) -> SentenceTransformer:

        """
        Get or load embedding model with caching.
        """
        if model_name not in cls._model_cache:
            logger.info(f" Loading embedding model: {model_name} (first time)")
            model = SentenceTransformer(model_name)
            cls._model_cache[model_name] = model
            logger.info(f" Model {model_name} loaded and cached")
        else:
            logger.debug(f" Using cached model: {model_name}")
        
        return cls._model_cache[model_name]
    
    @classmethod
    def embed_text(cls, text: str, model_name: str) -> List[float]:

        """
        Generate embedding vector for single text chunk. (single search qurey)
        """
        model = cls.get_model(model_name)
        
        # encode() returns numpy array, convert to list for JSON
        embedding = model.encode(text, convert_to_numpy=True)
        return embedding.tolist()
    
    @classmethod
    def embed_batch(cls, texts: List[str], model_name: str) -> List[List[float]]:

        """
        Generate embeddings for multiple texts (batch processing). (ex search whole doucment)
        """
        model = cls.get_model(model_name)
        
        
        embeddings = model.encode(
            texts,
            convert_to_numpy=True,
            show_progress_bar=False
        )
        
        return [emb.tolist() for emb in embeddings]
    
    @classmethod
    def clear_cache(cls):

        """
        Clear all cached models from memory. (Ai told me to do it)
        
        Use cases:
        - Deployment/updates
        - Memory pressure
        - Switching models
        """
        logger.info(" Clearing embedding model cache")
        cls._model_cache.clear()
    
    @classmethod
    def get_cache_info(cls) -> dict:

        """Get information about cached models."""
        return {
            'cached_models': list(cls._model_cache.keys()),
            'cache_size': len(cls._model_cache)
        }
