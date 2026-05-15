"""
Maps raw questionnaire answers to concrete RAG configuration values.
"""


REQUIRED_QUESTIONNAIRE_FIELDS = (
    "language",
    "use_case",
    "reference",
    "temperature",
    "top_p",
    "metadata",
    "chunking_strategy",
)


def embedding_reranker(language, use_case):
    # Pick the embedding + reranker pair for the given language/quality tradeoff.
    if language == "english":
        if use_case == "fast":
            return {
                "embedding_model": "all-MiniLM-L6-v2",
                "reranker_model":  "cross-encoder/ms-marco-MiniLM-L-6-v2",
            }
        if use_case == "balanced":
            return {
                "embedding_model": "all-mpnet-base-v2",
                "reranker_model":  "cross-encoder/ms-marco-MiniLM-L-6-v2",
            }
        if use_case == "quality":
            return {
                "embedding_model": "intfloat/e5-large-v2",
                "reranker_model":  "cross-encoder/ms-marco-MiniLM-L-12-v2",
            }
    # Multilingual / Arabic fall through to BGE-M3 regardless of use_case.
    return {
        "embedding_model": "BAAI/bge-m3",
        "reranker_model":  "BAAI/bge-reranker-v2-m3",
    }


def top_k(top_k_value):
    return 5 if top_k_value == "main" else 10


def temperature(temperature_value):
    return {"precise": 0.2, "balanced": 0.5}.get(temperature_value, 0.8)


def top_p(top_p_value):
    return {"strict": 0.2, "balanced": 0.5}.get(top_p_value, 0.9)


def reference(reference_value):
    return reference_value == "yes"


def add_metadata(response):
    return str(response).lower().strip() == "yes"


CHUNKING_STRATEGY_BY_CONTENT = {
    "slide deck":     "page-based",
    "meeting notes":  "large-overlapping",
    "article":        "paragraph-based",
    "manual":         "hierarchical",
    "research paper": "semantic",
    "policy":         "document-structure",
}


def determine_chunking_strategy(response):
    # Map a content-type label to the chunking strategy that suits it best.
    response_lower = str(response).lower().strip()
    for keyword, strategy in CHUNKING_STRATEGY_BY_CONTENT.items():
        if keyword in response_lower:
            return strategy
    return "fixed-length"
