from dataclasses import dataclass


@dataclass
class EmbeddingModelConfig:
    model_name: str
    dimension: int
    collection_key: str
    description: str


EMBEDDING_MODELS: dict[str, EmbeddingModelConfig] = {
    'all-MiniLM-L6-v2': EmbeddingModelConfig(
        model_name='sentence-transformers/all-MiniLM-L6-v2',
        dimension=384,
        collection_key='minilm',
        description='Fast - Low resources, good quality',
    ),
    'all-mpnet-base-v2': EmbeddingModelConfig(
        model_name='sentence-transformers/all-mpnet-base-v2',
        dimension=768,
        collection_key='mpnet',
        description='Balanced - Speed vs quality',
    ),
    'intfloat/e5-large-v2': EmbeddingModelConfig(
        model_name='intfloat/e5-large-v2',
        dimension=1024,
        collection_key='e5_large',
        description='Quality - Best semantic match',
    ),
    'BAAI/bge-m3': EmbeddingModelConfig(
        model_name='BAAI/bge-m3',
        dimension=1024,
        collection_key='bge_m3',
        description='Multilingual - English + Arabic + 100+ languages',
    ),
}


class ModelSelector:

    @staticmethod
    def get_model_config(embedding_model_name: str) -> EmbeddingModelConfig:
        """
        Look up embedding configuration by the model name stored in WorkspaceConfig.

        Args:
            embedding_model_name: The exact value from WorkspaceConfig.embedding_model
                                  (e.g. "all-MiniLM-L6-v2", "BAAI/bge-m3").
        """
        config = EMBEDDING_MODELS.get(embedding_model_name)
        if config is None:
            raise ValueError(
                f"Unknown embedding model: {embedding_model_name!r}. "
                f"Supported: {list(EMBEDDING_MODELS.keys())}"
            )
        return config

    @staticmethod
    def get_collection_name(collection_key: str) -> str:
        """Each embedding model type gets its own Qdrant collection."""
        return f"documents__{collection_key}"

    @staticmethod
    def list_supported_models() -> dict:
        """Return all supported models for reference."""
        return {
            key: {
                'model_name': cfg.model_name,
                'dimension': cfg.dimension,
                'description': cfg.description,
            }
            for key, cfg in EMBEDDING_MODELS.items()
        }
