"""
Workspace RAG query service.

Single entry point used by both the web chat view and the external
`/api/v1/query` endpoint. Keeps the embedding → Qdrant → rerank → LLM
flow in one place so behavior cannot drift between the two callers.
"""

import requests
from langdetect import DetectorFactory, LangDetectException, detect

from documents.services.embedding_service import EmbeddingService
from documents.services.qdrant_service import QdrantService
from pipeline.services.pipeline_registry import get_pipeline

DetectorFactory.seed = 0


EMBEDDING_MODEL_COLLECTION_SUFFIX = {
    "all-MiniLM-L6-v2":       "minilm",
    "all-mpnet-base-v2":      "mpnet",
    "intfloat/e5-large-v2":   "e5_large",
    "BAAI/bge-m3":            "bge_m3",
}

OLLAMA_URL         = "http://ollama:11434/api/generate"

OLLAMA_MODEL       = "llama3:latest"
OLLAMA_TITLE_MODEL = "llama3:8b-instruct-q4_0"

STRICT_TOP_P = 0.2
STRICT_INSTRUCTION = "Use only the provided context. Do not use external knowledge.\n\n"

LANGUAGE_NAMES = {
    "ar": "Arabic",
    "en": "English",
}


def _detect_language_instruction(query):
    try:
        code = detect(query)
    except LangDetectException:
        return ""
    name = LANGUAGE_NAMES.get(code)
    if name:
        return f"Respond in {name}.\n\n"
    # Fall-through for any other detected language — let the LLM mirror it.
    return "Respond in the same language as the question.\n\n"

NO_DOCS_REPLY = (
    "No documents have been uploaded to this workspace yet. "
    "Please upload documents first, then ask your question."
)

REINDEX_REQUIRED_REPLY = (
    "This workspace's embedding or chunking settings have changed since its "
    "documents were indexed, so the existing vectors can't be searched. "
    "Please re-upload (or re-index) the documents to use the new configuration."
)


class QueryResult:
    """Plain container so callers can destructure cleanly."""

    __slots__ = ("answer", "ranked_chunks", "sources", "is_citation", "metadata_flag", "no_documents")

    def __init__(self, answer, ranked_chunks, sources, is_citation, metadata_flag, no_documents=False):
        self.answer        = answer
        self.ranked_chunks = ranked_chunks
        self.sources       = sources
        self.is_citation   = is_citation
        self.metadata_flag = metadata_flag
        self.no_documents  = no_documents


def run_query(workspace, query):
    """
    Run the full RAG pipeline for `query` against `workspace`.

    Returns a `QueryResult`. The caller decides how to surface citations
    (text appendix in the web flow, structured JSON in the external API).
    """
    config = workspace.config
    embedding_model_name = config.embedding_model
    is_citation   = config.is_citation
    metadata_flag = config.metadata_flag

    pipeline    = get_pipeline(workspace.workspace_id, config)
    reranker    = pipeline["reranker"]
    temperature = pipeline["temperature"]
    top_p       = pipeline["top_p"]
    top_k       = pipeline["top_k"]

    embedded_query = EmbeddingService.embed_text(query, embedding_model_name)

    collection_suffix = EMBEDDING_MODEL_COLLECTION_SUFFIX[embedding_model_name]
    qdrant = QdrantService(host="qdrant", port=6333)
    chunks = qdrant.search(
        collection_name=f"documents__{collection_suffix}",
        workspace_id=workspace.workspace_id,
        query_vector=embedded_query,
        top_k=int(top_k * 2.5),
    )

    if not chunks:
        has_documents = workspace.documents.exists()
        answer = REINDEX_REQUIRED_REPLY if has_documents else NO_DOCS_REPLY
        return QueryResult(
            answer=answer,
            ranked_chunks=[],
            sources=[],
            is_citation=is_citation,
            metadata_flag=metadata_flag,
            no_documents=True,
        )

    pairs  = [(query, chunk["payload"]["text"]) for chunk in chunks]
    scores = reranker.predict(pairs)
    ranked_chunks = sorted(zip(chunks, scores), key=lambda x: x[1], reverse=True)

    top_ranked = ranked_chunks[:top_k]
    context = "\n\n".join(chunk["payload"]["text"] for chunk, _ in top_ranked)

    # Cross-encoder scores ≤ 0 indicate irrelevant chunks; drop them from
    # the citation set even when citations were requested.
    sources = []
    seen = set()
    for chunk, score in top_ranked:
        if score <= 0:
            continue
        payload = chunk["payload"]
        title   = payload.get("document_title") or payload.get("source", "Unknown")
        section = payload.get("section") or payload.get("page", "?")
        key = (title, section)
        if key in seen:
            continue
        seen.add(key)
        sources.append(payload)

    strict_prefix   = STRICT_INSTRUCTION if top_p == STRICT_TOP_P else ""
    language_prefix = _detect_language_instruction(query)
    prompt = (
        f"{language_prefix}"
        f"{strict_prefix}"
        f"Answer the following question based on the context:\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {query}"
    )
    response = requests.post(
        OLLAMA_URL,
        json={
            "model":       OLLAMA_MODEL,
            "prompt":      prompt,
            "temperature": temperature,
            "top_p":       top_p,
            "options":     {"top_k": top_k},
            "stream":      False,
        },
    )
    if response.status_code == 200:
        answer = response.json().get("response", "No response from LLaMA")
    else:
        answer = f"Error generating response: {response.status_code}"

    return QueryResult(
        answer=answer,
        ranked_chunks=ranked_chunks,
        sources=sources,
        is_citation=is_citation,
        metadata_flag=metadata_flag,
    )
