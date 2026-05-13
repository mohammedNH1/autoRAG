from dataclasses import dataclass
from transformers import AutoTokenizer

from .file_parsers import extract_text
from .chunking_strategies import (
    split_text_into_chunks,
    split_text_large_overlap,
    split_text_semantic,
    split_text_by_structure,
    split_text_by_page,
    split_text_by_paragraph,
    split_text_hierarchical,
)

# ─── Tokenizers — loaded once at startup ─────────────────────────────────────

BERT = AutoTokenizer.from_pretrained('bert-base-uncased')  # MiniLM, MPNet, E5
BGE  = AutoTokenizer.from_pretrained('BAAI/bge-m3')        # BGE-M3 (multilingual)

# ─── Embedding model registry ────────────────────────────────────────────────


@dataclass
class EmbeddingModelConfig:
    model_name: str
    tokenizer:  object
    max_tokens: int


EMBEDDING_MODELS: dict[str, EmbeddingModelConfig] = {
    'minilm':   EmbeddingModelConfig('MiniLM',   BERT, 256),
    'mpnet':    EmbeddingModelConfig('mpnet',    BERT, 384),
    'e5_large': EmbeddingModelConfig('e5-large', BERT, 512),
    'bge_m3':   EmbeddingModelConfig('bge-m3',   BGE,  512),
}

_STRATEGIES = frozenset(
    {'fixed-length', 'large-overlapping', 'semantic', 'document-structure',
     'page-based', 'paragraph-based', 'hierarchical'}
)

# ─── Main pipeline ───────────────────────────────────────────────────────────


def parse_document_into_chunks(
    file_path:    str,
    model_key:    str   = 'minilm',
    strategy:     str   = 'simple',
    chunk_size:   int   = 100,
    overlap:      int   = 10,
    threshold:    float = 0.5,
    doc_metadata: dict  = None,
) -> list[dict]:
    """
    Extract text from any supported file and split into embedding-ready chunks.
    """
    if model_key not in EMBEDDING_MODELS:
        raise ValueError(
            f"Unknown model_key '{model_key}'. "
            f"Choose from: {list(EMBEDDING_MODELS.keys())}"
        )
    if strategy not in _STRATEGIES:
        raise ValueError(
            f"Unknown strategy '{strategy}'. "
            f"Choose from: {sorted(_STRATEGIES)}"
        )

    config     = EMBEDDING_MODELS[model_key]
    tokenizer  = config.tokenizer
    max_tokens = config.max_tokens
    extra_meta = doc_metadata or {}

    sections   = extract_text(file_path)
    all_chunks = []

    for section_text, section_number, language in sections:
        if not section_text.strip():
            continue

        if strategy == 'fixed-length':
            page_chunks = split_text_into_chunks(section_text, chunk_size, overlap)
        elif strategy == 'large-overlapping':
            page_chunks = split_text_large_overlap(section_text, tokenizer, max_tokens)
        elif strategy == 'semantic':
            page_chunks = split_text_semantic(section_text, tokenizer, max_tokens, threshold)
        elif strategy == 'document-structure':
            page_chunks = split_text_by_structure(section_text, tokenizer, max_tokens)
        elif strategy == 'page-based':
            page_chunks = split_text_by_page(section_text, tokenizer, max_tokens)
        elif strategy == 'paragraph-based':
            page_chunks = split_text_by_paragraph(section_text, tokenizer, max_tokens)
        elif strategy == 'hierarchical':
            page_chunks = split_text_hierarchical(section_text, tokenizer, max_tokens)

        for chunk_index, chunk_text in enumerate(page_chunks):
            if not chunk_text.strip():
                continue
            all_chunks.append({
                "text": chunk_text,
                "metadata": {
                    "source":      file_path,
                    "section":     section_number,
                    "language":    language,
                    "chunk_index": chunk_index,
                    "strategy":    strategy,
                    "model":       model_key,
                    "token_limit": max_tokens,
                    **extra_meta,
                },
            })

    return all_chunks
