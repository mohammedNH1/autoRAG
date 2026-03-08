"""
Job: "Which AI model should I use?" 
"""

from typing import Optional
from dataclasses import dataclass


@dataclass
class EmbeddingModelConfig:
    """Configuration for an embedding model."""
    model_name: str          # HuggingFace model name
    dimension: int           # Vector dimension
    collection_key: str      # Used in collection naming
    description: str


# Map your existing model names (from questionnaire) to vector configs
EMBEDDING_MODELS = {
    # Fast option (English)
    'all-MiniLM-L6-v2': EmbeddingModelConfig(
        model_name='sentence-transformers/all-MiniLM-L6-v2',
        dimension=384,
        collection_key='minilm',
        description='Fast - Low resources, good quality'
    ),
    
    # Balanced option (English)
    'all-mpnet-base-v2': EmbeddingModelConfig(
        model_name='sentence-transformers/all-mpnet-base-v2',
        dimension=768,
        collection_key='mpnet',
        description='Balanced - Speed vs quality'
    ),
    
    # Quality option (English)
    'intfloat/e5-large-v2': EmbeddingModelConfig(
        model_name='intfloat/e5-large-v2',
        dimension=1024,
        collection_key='e5_large',
        description='Quality - Best semantic match'
    ),
    
    # Multilingual option
    'BAAI/bge-m3': EmbeddingModelConfig(
        model_name='BAAI/bge-m3',
        dimension=1024,
        collection_key='bge_m3',
        description='Multilingual - English + Arabic + 100+ languages'
    ),
}


class ModelSelector:
    
    """
    This class translates our questionnaire's model name into technical details.
    """
    
    @staticmethod
    def get_model_config(embedding_model_name: str) -> EmbeddingModelConfig:

        """
        Get embedding configuration from model name stored in WorkspaceConfig.

        Args:
        embedding_model_name: The value from workspace.config.embedding_model
                            (e.g., "all-MiniLM-L6-v2", "BAAI/bge-m3") as a string .
        """
        # Handle both short names and full paths
        for key, config in EMBEDDING_MODELS.items():
            if key in embedding_model_name or embedding_model_name in config.model_name:
                return config
        
        # If not found, raise error
        raise ValueError(
            f"Unknown embedding model: {embedding_model_name}. "
            f"Supported models: {list(EMBEDDING_MODELS.keys())}"
        )
    
    @staticmethod
    def get_collection_name(collection_key: str) -> str:

        """
        Every embed has its own collection , every emebd type not user!!
        """
        return f"documents__{collection_key}"
    
    @staticmethod
    def list_supported_models() -> dict:
        
        """Return all supported models for reference.
        """
        return {
            key: {
                'model_name': config.model_name,
                'dimension': config.dimension,
                'description': config.description
            }
            for key, config in EMBEDDING_MODELS.items()
        }
