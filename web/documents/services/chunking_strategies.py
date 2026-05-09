import re
from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer
from langchain_text_splitters import RecursiveCharacterTextSplitter, CharacterTextSplitter

# Lazy-loaded — only instantiated the first time semantic chunking is used.
# Avoids loading a ~500 MB model on every app startup.
_sentence_model: SentenceTransformer | None = None


def _get_sentence_model() -> SentenceTransformer:
    global _sentence_model
    if _sentence_model is None:
        _sentence_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
    return _sentence_model


def enforce_token_limit(chunks: list[str], tokenizer, max_tokens: int) -> list[str]:
    """
    Safety pass: splits any chunk that exceeds max_tokens using the real tokenizer.
    LangChain uses char-count approximations; this is the authoritative final check.
    """
    safe_chunks = []
    for chunk in chunks:
        tokens = tokenizer.encode(chunk, add_special_tokens=False)
        if len(tokens) <= max_tokens:
            safe_chunks.append(chunk)
        else:
            for i in range(0, len(tokens), max_tokens):
                sub_chunk = tokenizer.decode(
                    tokens[i: i + max_tokens],
                    skip_special_tokens=True,
                    clean_up_tokenization_spaces=True,
                )
                safe_chunks.append(sub_chunk)
    return safe_chunks


# ── Strategy 1 ───────────────────────────────────────────────────────────────
# Simple overlapping word-based chunks
# Best for: quick baseline, short uniform documents

def split_text_into_chunks(text: str, chunk_size: int = 100, overlap: int = 10) -> list[str]:
    words = text.split()
    chunks = []
    for start_index in range(0, len(words), chunk_size - overlap):
        chunk_words = words[start_index: start_index + chunk_size]
        chunks.append(" ".join(chunk_words))
    return chunks


# ── Strategy 2 ───────────────────────────────────────────────────────────────
# Large overlapping token-aware chunks
# Best for: long dense docs, legal/technical text

def split_text_large_overlap(text: str, tokenizer, max_tokens: int,
                              overlap_tokens: int = 128) -> list[str]:
    # overlap_tokens=128 ≈ half of BERT's practical 256-token window
    tokens = tokenizer.encode(text, add_special_tokens=False)
    step   = max_tokens - overlap_tokens
    chunks = []
    for start_index in range(0, len(tokens), step):
        chunk_tokens = tokens[start_index: start_index + max_tokens]
        chunk = tokenizer.decode(
            chunk_tokens,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=True,
        )
        chunks.append(chunk)
    return chunks


# ── Strategy 3 ───────────────────────────────────────────────────────────────
# Semantic chunking — topic-boundary detection via cosine similarity
# Best for: mixed-topic docs, articles, reports

def split_text_semantic(text: str, tokenizer, max_tokens: int,
                        threshold: float = 0.5, min_sentences: int = 3) -> list[str]:
    # min_sentences=3: require at least 3 sentences before allowing a boundary split
    sentences = re.split(r'(?<=[.!?؟])\s+', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    if len(sentences) <= min_sentences:
        return [text]

    embeddings    = _get_sentence_model().encode(sentences, show_progress_bar=False)
    chunks        = []
    current_chunk = [sentences[0]]

    for i in range(1, len(sentences)):
        sim = cosine_similarity(
            embeddings[i - 1].reshape(1, -1),
            embeddings[i].reshape(1, -1),
        )[0][0]

        if sim < threshold and len(current_chunk) >= min_sentences:
            chunks.append(" ".join(current_chunk))
            current_chunk = [sentences[i]]
        else:
            current_chunk.append(sentences[i])

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return enforce_token_limit(chunks, tokenizer, max_tokens)


# ── Strategy 4 ───────────────────────────────────────────────────────────────
# Document-structure chunking — split on double newlines
# Best for: structured PDFs with clear section breaks

def split_text_by_structure(text: str, tokenizer, max_tokens: int) -> list[str]:
    splitter = CharacterTextSplitter(
        separator       = "\n\n",
        chunk_size      = max_tokens * 4,  # *4: approximate chars-per-token ratio
        chunk_overlap   = 0,
        length_function = len,
    )
    chunks = splitter.split_text(text)
    return enforce_token_limit(chunks, tokenizer, max_tokens)


# ── Strategy 5 ───────────────────────────────────────────────────────────────
# Page-based chunking — one chunk per PDF page / document section
# Best for: slides, reports where each page is self-contained

def split_text_by_page(page_text: str, tokenizer, max_tokens: int) -> list[str]:
    if not page_text.strip():
        return []
    splitter = CharacterTextSplitter(
        separator       = "\n",
        chunk_size      = max_tokens * 4,  # *4: approximate chars-per-token ratio
        chunk_overlap   = 0,
        length_function = len,
    )
    chunks = splitter.split_text(page_text)
    return enforce_token_limit(chunks, tokenizer, max_tokens)


# ── Strategy 6 ───────────────────────────────────────────────────────────────
# Paragraph-based chunking — recursive \n\n → \n → word fallback
# Best for: articles, books, essays

def split_text_by_paragraph(text: str, tokenizer, max_tokens: int) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        separators      = ["\n\n", "\n", " ", ""],
        chunk_size      = max_tokens * 4,  # *4: approximate chars-per-token ratio
        chunk_overlap   = 50,
        length_function = len,
    )
    chunks = splitter.split_text(text)
    return enforce_token_limit(chunks, tokenizer, max_tokens)


# ── Strategy 7 ───────────────────────────────────────────────────────────────
# Hierarchical chunking — \n\n → \n → sentence → word
# Best for: long structured docs — legal cases, technical manuals

def split_text_hierarchical(text: str, tokenizer, max_tokens: int) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        separators      = ["\n\n", "\n", ". ", " ", ""],
        chunk_size      = max_tokens * 4,  # *4: approximate chars-per-token ratio
        chunk_overlap   = 128,
        length_function = len,
    )
    chunks = splitter.split_text(text)
    return enforce_token_limit(chunks, tokenizer, max_tokens)
