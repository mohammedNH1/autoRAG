from sentence_transformers import SentenceTransformer, CrossEncoder
#from .chunking import chunking_strategy_initialize

pipeline_registry = {}


def build_pipeline(config):
    return {
        "embedding_model": SentenceTransformer(config.embedding_model),
        "reranker": CrossEncoder(config.re_ranker),
        "temperature": config.temperature,
        "top_p": config.top_p,
        "top_k": config.top_k,
    }


def get_pipeline(workspace_id, config):
    if workspace_id not in pipeline_registry:
        pipeline_registry[workspace_id] = build_pipeline(config)

    return pipeline_registry[workspace_id]


def invalidate_pipeline(workspace_id):
    if workspace_id in pipeline_registry:
        del pipeline_registry[workspace_id]
