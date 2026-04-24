import fitz                  # PyMuPDF - for reading PDF files
import re                    # for text cleaning and splitting
from dataclasses import dataclass
from langdetect import detect # for detecting language of text
import arabic_reshaper        # for fixing Arabic character shapes for NLP/embedding
from transformers import AutoTokenizer
from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,  # used by: paragraph, hierarchical
    CharacterTextSplitter,           # used by: structure, page
)


# ─────────────────────────────────────────────
# TOKENIZERS
# Load once at startup — 2 tokenizers cover all 4 models
# ─────────────────────────────────────────────

BERT = AutoTokenizer.from_pretrained('bert-base-uncased')  # covers MiniLM, MPNet, E5
BGE  = AutoTokenizer.from_pretrained('BAAI/bge-m3')        # covers BGE-M3 (multilingual)


# ─────────────────────────────────────────────
# EMBEDDING MODEL CONFIG
# Each model carries its own tokenizer and token limit.
# Pass the model key to parse_pdf_into_chunks — everything
# else (tokenizer, max_tokens) is resolved automatically.
# ─────────────────────────────────────────────

@dataclass
class EmbeddingModelConfig:
    model_name:  str
    tokenizer:   object  # the loaded tokenizer instance (BERT or BGE)
    max_tokens:  int     # safe token limit for chunking with this model


EMBEDDING_MODELS = {
    'minilm': EmbeddingModelConfig(
        model_name  = 'MiniLM',
        tokenizer   = BERT,
        max_tokens  = 256,   # MiniLM hard limit — trained on 256 tokens
    ),
    'mpnet': EmbeddingModelConfig(
        model_name  = 'mpnet',
        tokenizer   = BERT,
        max_tokens  = 384,   # window is 512 but quality drops at edges, 384 is safer
    ),
    'e5_large': EmbeddingModelConfig(
        model_name  = 'e5-large',
        tokenizer   = BERT,
        max_tokens  = 512,   # full context window, E5 uses it well
    ),
    'bge_m3': EmbeddingModelConfig(
        model_name  = 'bge-m3',
        tokenizer   = BGE,
        max_tokens  = 512,   # supports 8192 but 512 gives better RAG retrieval precision
    ),
}


# ─────────────────────────────────────────────
# LANGUAGE DETECTION
# ─────────────────────────────────────────────

def contains_arabic(text: str) -> bool:
    # Check if a string contains any Arabic characters.
    arabic_unicode_pattern = re.compile(r'[\u0600-\u06FF]')
    return bool(arabic_unicode_pattern.search(text))


def detect_dominant_language(text: str) -> str:
    """
    Detect the dominant language of a block of text.
    Used for metadata purposes (e.g. tagging chunks as 'ar' or 'en').
    """
    try:
        return detect(text)
    except:
        return "en"  # default to English if detection fails


# ─────────────────────────────────────────────
# TEXT PROCESSING
# ─────────────────────────────────────────────

def fix_arabic_characters(sentence: str) -> str:
    # Arabic text extracted from PDFs often has characters in their isolated form, and Left-to-Right.
    return arabic_reshaper.reshape(sentence)


def process_mixed_language_text(raw_text: str) -> str:
    sentences = re.split(r'(?<=[.!?؟।])\s+|\n', raw_text)

    processed_sentences = []
    for sentence in sentences:
        if contains_arabic(sentence):
            sentence = fix_arabic_characters(sentence)
        processed_sentences.append(sentence)

    return "\n\n".join(processed_sentences)  # preserve paragraph breaks


def clean_extracted_text(text: str) -> str:
     text = re.sub(r'\n{3,}', '\n\n', text)  # keep double newlines, collapse only 3+
     text = re.sub(r' +', ' ', text)          # collapse multiple spaces into one
     return text.strip()


# ─────────────────────────────────────────────
# SHARED HELPER
# Final accurate token check — used by all strategies
# that produce variable-length chunks
# ─────────────────────────────────────────────

def enforce_token_limit(chunks: list[str], tokenizer, max_tokens: int) -> list[str]:
    """
    Safety pass: if any chunk exceeds max_tokens, split it further.

    LangChain splits by character count (chunk_size = max_tokens * 4).
    This is an approximation — 1 token ≈ 4 chars in English but varies.
    enforce_token_limit() does the final accurate check using the real tokenizer.

    Args:
        chunks:     List of text chunks to check.
        tokenizer:  The model's tokenizer.
        max_tokens: The model's token limit from EmbeddingModelConfig.

    Returns a new list of chunks, all within the token limit.
    """
    safe_chunks = []
    for chunk in chunks:
        tokens = tokenizer.encode(chunk, add_special_tokens=False)
        if len(tokens) <= max_tokens:
            safe_chunks.append(chunk)
        else:
            # Too long — split into token-accurate sub-chunks
            for i in range(0, len(tokens), max_tokens):
                sub_chunk = tokenizer.decode(
                    tokens[i: i + max_tokens],
                    skip_special_tokens=True,
                    clean_up_tokenization_spaces=True
)
    return safe_chunks


# ─────────────────────────────────────────────
# CHUNKING — STRATEGY 1
# Simple overlapping word-based chunks
# Best for: quick baseline, short uniform documents
# ─────────────────────────────────────────────

def split_text_into_chunks(text: str, chunk_size: int = 100, overlap: int = 10) -> list[str]:
    """
    Split a long text into smaller overlapping word-based chunks.

    Args:
        text:       The full text to split.
        chunk_size: Number of words per chunk (default: 100).
        overlap:    Number of words to repeat from the previous chunk (default: 10).

    Returns a list of text chunk strings.
    """
    words = text.split()
    chunks = []

    for start_index in range(0, len(words), chunk_size - overlap):
        chunk_words = words[start_index: start_index + chunk_size]
        chunk = " ".join(chunk_words)
        chunks.append(chunk)

    return chunks


# ─────────────────────────────────────────────
# CHUNKING — STRATEGY 2
# Large overlapping token-aware chunks
# Best for: long dense docs, legal/technical text
# ─────────────────────────────────────────────

def split_text_large_overlap(text: str, tokenizer, max_tokens: int, overlap_tokens: int = 128) -> list[str]:
    """
    Split text into large token-aware chunks with significant overlap.
    Uses the model's actual tokenizer so chunk sizes are accurate.

    Args:
        text:           The full text to split.
        tokenizer:      From EmbeddingModelConfig.tokenizer.
        max_tokens:     From EmbeddingModelConfig.max_tokens.
        overlap_tokens: Tokens to repeat from the previous chunk (default: 128).

    Returns a list of text chunk strings.
    """
    tokens = tokenizer.encode(text, add_special_tokens=False)
    step   = max_tokens - overlap_tokens
    chunks = []

    for start_index in range(0, len(tokens), step):
        chunk_tokens = tokens[start_index: start_index + max_tokens]
        chunk        = tokenizer.decode(chunk_tokens, skip_special_tokens=True,
                                        clean_up_tokenization_spaces=True)  # ← add this
        chunks.append(chunk)

    return chunks


# ─────────────────────────────────────────────
# CHUNKING — STRATEGY 3
# Semantic chunking
# Best for: mixed-topic docs, articles, reports
# ─────────────────────────────────────────────
# ── module level — loads once when the file is imported ──
SENTENCE_MODEL = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2') #design choice , need discussion  


def split_text_semantic(text: str, tokenizer, max_tokens: int,
                        threshold: float = 0.5, min_sentences: int = 3) -> list[str]:
    """
    Split text based on semantic similarity between sentences.
    Uses MiniLM for boundary detection, then enforce_token_limit() for size.

    Args:
        text:          The full text to split.
        tokenizer:     From EmbeddingModelConfig.tokenizer — for token limit check.
        max_tokens:    From EmbeddingModelConfig.max_tokens — for token limit check.
        threshold:     Cosine similarity cutoff. Lower = more chunks.
        min_sentences: Minimum sentences before a chunk boundary is allowed.

    Returns a list of text chunk strings, all within max_tokens.
    """
    sentences = re.split(r'(?<=[.!?؟])\s+', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    if len(sentences) <= min_sentences:
        return [text]

    embeddings    = SENTENCE_MODEL.encode(sentences, show_progress_bar=False)
    chunks        = []
    current_chunk = [sentences[0]]

    for i in range(1, len(sentences)):
        sim = cosine_similarity(
            embeddings[i - 1].reshape(1, -1),
            embeddings[i].reshape(1, -1)
        )[0][0]

        if sim < threshold and len(current_chunk) >= min_sentences:
            chunks.append(" ".join(current_chunk))
            current_chunk = [sentences[i]]
        else:
            current_chunk.append(sentences[i])

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return enforce_token_limit(chunks, tokenizer, max_tokens)


# ─────────────────────────────────────────────
# CHUNKING — STRATEGY 4
# Document-structure chunking
# LangChain: CharacterTextSplitter on double newlines
# Best for: structured PDFs with clear section breaks
# ─────────────────────────────────────────────

def split_text_by_structure(text: str, tokenizer, max_tokens: int) -> list[str]:
    """
    Split text on double newlines using LangChain CharacterTextSplitter.

    Why LangChain:
        CharacterTextSplitter splits strictly on a chosen separator (\n\n).
        This maps directly to section/paragraph breaks in structured documents.
        Simpler and more reliable than manual heading regex detection.

    How it works:
        1. CharacterTextSplitter splits on \n\n (section boundary).
        2. chunk_size = max_tokens * 4 (approx chars — 1 token ≈ 4 chars).
        3. enforce_token_limit() does a final accurate token check.

    Args:
        text:       The full text to split.
        tokenizer:  From EmbeddingModelConfig.tokenizer — for token limit check.
        max_tokens: From EmbeddingModelConfig.max_tokens.

    Returns a list of text chunk strings, all within max_tokens.
    """
    splitter = CharacterTextSplitter(
        separator       = "\n\n",          # split on double newline = section break
        chunk_size      = max_tokens * 4,  # approx chars — 1 token ≈ 4 chars in English
        chunk_overlap   = 0,               # no overlap — each section is self-contained
        length_function = len,
    )
    chunks = splitter.split_text(text)
    return enforce_token_limit(chunks, tokenizer, max_tokens)


# ─────────────────────────────────────────────
# CHUNKING — STRATEGY 5
# Page-based chunking
# LangChain: CharacterTextSplitter on single newlines
# Best for: slides, reports — each page is a self-contained unit
# ─────────────────────────────────────────────

def split_text_by_page(page_text: str, tokenizer, max_tokens: int) -> list[str]:
    """
    Treat each PDF page as one chunk, split further only if too long.

    Why LangChain:
        CharacterTextSplitter with separator="\n" keeps the page as one chunk
        unless it exceeds the limit — then splits on line boundaries cleanly.
        Better than enforce_token_limit alone which cuts mid-sentence.

    How it works:
        1. Try to keep the full page as one chunk.
        2. If too long, split on \n (line boundaries).
        3. enforce_token_limit() does a final accurate token check.

    Args:
        page_text:  The full cleaned text of one PDF page.
        tokenizer:  From EmbeddingModelConfig.tokenizer — for token limit check.
        max_tokens: From EmbeddingModelConfig.max_tokens.

    Returns a list of text chunk strings, all within max_tokens.
    """
    if not page_text.strip():
        return []

    splitter = CharacterTextSplitter(
        separator       = "\n",            # split on line breaks when page is too long
        chunk_size      = max_tokens * 4,  # approx chars
        chunk_overlap   = 0,
        length_function = len,
    )
    chunks = splitter.split_text(page_text)
    return enforce_token_limit(chunks, tokenizer, max_tokens)


# ─────────────────────────────────────────────
# CHUNKING — STRATEGY 6
# Paragraph-based chunking
# LangChain: RecursiveCharacterTextSplitter with paragraph fallback
# Best for: articles, books, essays
# ─────────────────────────────────────────────

def split_text_by_paragraph(text: str, tokenizer, max_tokens: int) -> list[str]:
    """
    Split text at paragraph boundaries using LangChain RecursiveCharacterTextSplitter.

    Why LangChain:
        RecursiveCharacterTextSplitter tries separators in order:
        \n\n → \n → " " → ""
        This solves the problem where split(\n\n) alone produced one giant chunk
        because PyMuPDF extractions often have no double newlines.
        LangChain falls back to single newline automatically — no manual fix needed.

    How it works:
        1. Try \n\n (paragraph break) first.
        2. If chunks still too large, try \n (line break).
        3. If still too large, try " " (word break).
        4. enforce_token_limit() does a final accurate token check.

    Args:
        text:       The full text to split.
        tokenizer:  From EmbeddingModelConfig.tokenizer — for token limit check.
        max_tokens: From EmbeddingModelConfig.max_tokens.

    Returns a list of text chunk strings, all within max_tokens.
    """
    splitter = RecursiveCharacterTextSplitter(
        separators      = ["\n\n", "\n", " ", ""],  # paragraph → line → word → char
        chunk_size      = max_tokens * 4,            # approx chars
        chunk_overlap   = 50,                        # small overlap to avoid cutting mid-idea
        length_function = len,
    )
    chunks = splitter.split_text(text)
    return enforce_token_limit(chunks, tokenizer, max_tokens)


# ─────────────────────────────────────────────
# CHUNKING — STRATEGY 7
# Hierarchical chunking
# LangChain: RecursiveCharacterTextSplitter with sentence-aware separators
# Best for: long structured docs — legal cases, technical manuals
# ─────────────────────────────────────────────

def split_text_hierarchical(text: str, tokenizer, max_tokens: int) -> list[str]:
    """
    Two-level split: sections then sentences, using LangChain RecursiveCharacterTextSplitter.

    Why LangChain:
        RecursiveCharacterTextSplitter tries separators from coarsest to finest:
        \n\n (section) → \n (line) → ". " (sentence) → " " (word)
        This naturally implements the two-level hierarchy without manual heading
        detection — works even when PDFs have no headings at all.
        chunk_overlap=128 ensures context carries across boundaries.

    How it works:
        1. Try \n\n first — catches section/paragraph breaks.
        2. Fall back to \n — catches line breaks within sections.
        3. Fall back to ". " — catches sentence boundaries.
        4. Fall back to " " — word boundaries as last resort.
        5. enforce_token_limit() does a final accurate token check.

    Args:
        text:       The full text to split.
        tokenizer:  From EmbeddingModelConfig.tokenizer — for token counting.
        max_tokens: From EmbeddingModelConfig.max_tokens.

    Returns a list of text chunk strings, all within max_tokens.
    """
    splitter = RecursiveCharacterTextSplitter(
        separators      = ["\n\n", "\n", ". ", " ", ""],  # coarse → fine hierarchy
        chunk_size      = max_tokens * 4,                  # approx chars
        chunk_overlap   = 128,                             # overlap preserves cross-boundary context
        length_function = len,
    )
    chunks = splitter.split_text(text)
    return enforce_token_limit(chunks, tokenizer, max_tokens)


# ─────────────────────────────────────────────
# PDF EXTRACTION
# ─────────────────────────────────────────────

def extract_text_from_page(page) -> tuple[str, str]:
    # Use "blocks" to preserve paragraph boundaries
    blocks = page.get_text("blocks")  # returns list of (x0,y0,x1,y1,text,block_no,block_type)

    if not blocks:
        return "", "en"

    # Join blocks with double newline — each block is a paragraph
    raw_text = "\n\n".join(
        b[4].strip() for b in blocks
        if b[4].strip() and b[6] == 0  # b[6]==0 means text block, not image
    )

    if not raw_text.strip():
        return "", "en"

    processed_text    = process_mixed_language_text(raw_text)
    dominant_language = detect_dominant_language(processed_text)

    return processed_text, dominant_language
# ─────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────

def parse_pdf_into_chunks(
    file_path:  str,
    model_key:  str   = 'minilm',   # key from EMBEDDING_MODELS
    strategy:   str   = 'simple',   # simple | large | semantic | structure | page | paragraph | hierarchical
    chunk_size: int   = 100,        # [simple] words per chunk
    overlap:    int   = 10,         # [simple] overlapping words
    threshold:  float = 0.5,        # [semantic] cosine similarity cutoff
) -> list[dict]:
    """
    Full pipeline: extract text from a PDF and split into chunks for RAG.

    Tokenizer and max_tokens are resolved automatically from model_key.

    Args:
        file_path:  Path to the PDF file.
        model_key:  Key from EMBEDDING_MODELS. One of:
                        'minilm'    (256 tokens, BERT tokenizer)
                        'mpnet'     (384 tokens, BERT tokenizer)
                        'e5_large'  (512 tokens, BERT tokenizer)
                        'bge_m3'    (512 tokens, BGE  tokenizer)
        strategy:   Chunking strategy. One of:
                        'simple'       — word-based overlap, fast baseline
                        'large'        — token-aware large overlap, best for legal/technical
                        'semantic'     — topic-boundary detection, best for mixed-topic docs
                        'structure'    — LangChain split on \n\n, best for structured PDFs
                        'page'         — LangChain split on \n, best for slides/reports
                        'paragraph'    — LangChain recursive \n\n→\n→word, best for articles/books
                        'hierarchical' — LangChain recursive \n\n→\n→sentence, best for long structured docs
        chunk_size: [simple only] words per chunk.
        overlap:    [simple only] overlapping words between chunks.
        threshold:  [semantic only] cosine similarity cutoff for topic boundary.

    Returns a list of dicts:
        {
            "text":     chunk text,
            "metadata": {
                "source":       PDF file path,
                "page":         page number (1-based),
                "language":     dominant language ('ar' or 'en'),
                "chunk_index":  index of chunk within the page (0-based),
                "strategy":     chunking strategy used,
                "model":        embedding model key,
                "token_limit":  max_tokens for this model
            }
        }
    """
    if model_key not in EMBEDDING_MODELS:
        raise ValueError(f"Unknown model_key '{model_key}'. Choose from: {list(EMBEDDING_MODELS.keys())}")

    config     = EMBEDDING_MODELS[model_key]
    tokenizer  = config.tokenizer    # BERT or BGE, already loaded at startup
    max_tokens = config.max_tokens   # 256 / 384 / 512 depending on model

    pdf_document = fitz.open(file_path)
    all_chunks   = []

    for page_number, page in enumerate(pdf_document):
        page_text, dominant_language = extract_text_from_page(page)
        cleaned_text = clean_extracted_text(page_text)

        if not cleaned_text:
            continue

        # ── Pick strategy — tokenizer + max_tokens flow in automatically ──
        if strategy == 'simple':
            page_chunks = split_text_into_chunks(cleaned_text, chunk_size, overlap)

        elif strategy == 'large':
            page_chunks = split_text_large_overlap(cleaned_text, tokenizer, max_tokens)

        elif strategy == 'semantic':
            page_chunks = split_text_semantic(cleaned_text, tokenizer, max_tokens, threshold)

        elif strategy == 'structure':
            page_chunks = split_text_by_structure(cleaned_text, tokenizer, max_tokens)

        elif strategy == 'page':
            page_chunks = split_text_by_page(cleaned_text, tokenizer, max_tokens)

        elif strategy == 'paragraph':
            page_chunks = split_text_by_paragraph(cleaned_text, tokenizer, max_tokens)

        elif strategy == 'hierarchical':
            page_chunks = split_text_hierarchical(cleaned_text, tokenizer, max_tokens)

        else:
            raise ValueError(f"Unknown strategy '{strategy}'. Choose: simple, large, semantic, structure, page, paragraph, hierarchical")

        for chunk_index, chunk_text in enumerate(page_chunks):
            if not chunk_text.strip():
                continue
            all_chunks.append({
                "text": chunk_text,
                "metadata": {
                    "source":      file_path,
                    "page":        page_number + 1,
                    "language":    dominant_language,
                    "chunk_index": chunk_index,
                    "strategy":    strategy,
                    "model":       model_key,
                    "token_limit": max_tokens,
                }
            })

    pdf_document.close()
    return all_chunks


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    from pathlib import Path
    FILE = str(Path(__file__).parent / "singapore-court-case1.pdf")

    strategies = ['simple', 'large', 'semantic', 'structure', 'page', 'paragraph', 'hierarchical']

    for strategy in strategies:
        chunks = parse_pdf_into_chunks(FILE, model_key='minilm', strategy=strategy)
        print(f"[{strategy:<12}] Total chunks: {len(chunks)}")