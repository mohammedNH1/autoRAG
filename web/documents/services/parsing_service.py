import fitz                  # PyMuPDF - for reading PDF files
import re                    # for text cleaning and splitting
from dataclasses import dataclass
from langdetect import detect # for detecting language of text
import arabic_reshaper        # for fixing Arabic character shapes for NLP/embedding
from transformers import AutoTokenizer
from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer


# ─────────────────────────────────────────────
# TOKENIZERS
# Load once at startup — 2 tokenizers cover all 4 models
# ─────────────────────────────────────────────

BERT = AutoTokenizer.from_pretrained('bert-base-uncased')  # covers MiniLM, MPNet, E5
BGE  = AutoTokenizer.from_pretrained('BAAI/bge-m3')        # covers BGE-M3 (multilingual)


# ─────────────────────────────────────────────
# EMBEDDING MODEL CONFIG
# Each model carries its own tokenizer and token limit.
# ─────────────────────────────────────────────

@dataclass
class EmbeddingModelConfig:
    model_name:     str
    tokenizer:      object  # the loaded tokenizer instance (BERT or BGE)
    max_tokens:     int     # safe token limit for chunking with this model


EMBEDDING_MODELS = {
    'minilm': EmbeddingModelConfig(
        model_name     = 'sentence-transformers/all-MiniLM-L6-v2',
        tokenizer      = BERT,
        max_tokens     = 256,   # MiniLM hard limit — trained on 256 tokens
    ),
    'mpnet': EmbeddingModelConfig(
        model_name     = 'sentence-transformers/all-mpnet-base-v2',
        tokenizer      = BERT,
        max_tokens     = 384,   # window is 512 but quality drops at edges, 384 is safer
    ),
    'e5_large': EmbeddingModelConfig(
        model_name     = 'intfloat/e5-large-v2',
        tokenizer      = BERT,
        max_tokens     = 512,   # full context window, E5 uses it well
    ),
    'bge_m3': EmbeddingModelConfig(
        model_name     = 'BAAI/bge-m3',
        tokenizer      = BGE,
        max_tokens     = 512,   # supports 8192 but 512 gives better RAG retrieval precision
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
    """
    Process text that may contain both Arabic and English sentences.

    Splits the text into sentences, then checks each sentence individually.
    Arabic sentences are reshaped to fix character joining.
    English sentences are left unchanged.

    This sentence-level approach avoids mistakenly reshaping English text
    when a page contains both languages.

    Returns the fully processed text as a single string.
    """
    # Split on punctuation followed by whitespace, or on newlines
    sentences = re.split(r'(?<=[.!?؟।])\s+|\n', raw_text)

    processed_sentences = []
    for sentence in sentences:
        if contains_arabic(sentence):
            sentence = fix_arabic_characters(sentence)
        processed_sentences.append(sentence)

    return " ".join(processed_sentences)


def clean_extracted_text(text: str) -> str:
    text = re.sub(r'\n+', '\n', text)   # collapse multiple newlines into one
    text = re.sub(r' +', ' ', text)     # collapse multiple spaces into one
    return text.strip()                  # remove leading/trailing whitespace


# ─────────────────────────────────────────────
# SHARED HELPER
# Used by strategies that produce variable-length chunks
# to guarantee nothing exceeds the model's token limit
# ─────────────────────────────────────────────

def enforce_token_limit(chunks: list[str], tokenizer, max_tokens: int) -> list[str]:
    """
    Safety pass: if any chunk exceeds max_tokens, split it further.

    Args:
        chunks:     List of text chunks to check.
        tokenizer:  The model's tokenizer — used to count tokens accurately.
        max_tokens: The model's token limit from EmbeddingModelConfig.
    Returns a new list of chunks, all within the token limit.
    """
    safe_chunks = []
    for chunk in chunks:
        tokens = tokenizer.encode(chunk, add_special_tokens=False)
        if len(tokens) <= max_tokens:
            safe_chunks.append(chunk)           # fits — keep as-is
        else:
            # Too long — split into token-accurate sub-chunks
            for i in range(0, len(tokens), max_tokens):
                sub_chunk = tokenizer.decode(tokens[i: i + max_tokens])
                safe_chunks.append(sub_chunk)
    return safe_chunks


# ─────────────────────────────────────────────
# CHUNKING — STRATEGY 1
# Simple overlapping word-based chunks
# ─────────────────────────────────────────────

def split_text_into_chunks(text: str, chunk_size: int = 100, overlap: int = 10) -> list[str]:
    """
    Split a long text into smaller overlapping chunks for embedding.

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
    step   = max_tokens - overlap_tokens  # how far to advance each iteration
    chunks = []

    for start_index in range(0, len(tokens), step):
        chunk_tokens = tokens[start_index: start_index + max_tokens]
        chunk        = tokenizer.decode(chunk_tokens)
        chunks.append(chunk)

    return chunks


# ─────────────────────────────────────────────
# CHUNKING — STRATEGY 3
# Semantic chunking
# ─────────────────────────────────────────────

def split_text_semantic(text: str, tokenizer, max_tokens: int,
                        threshold: float = 0.5, min_sentences: int = 3) -> list[str]:
    """
    Split text into chunks based on semantic similarity between sentences.

    How it works:
        1. Split text into individual sentences.
        2. Embed every sentence using MiniLM (fast, good enough for boundary detection).
        3. Compare each sentence to the next using cosine similarity.
        4. When similarity drops below the threshold, a topic shift is detected
           and a new chunk begins.
        5. enforce_token_limit() ensures no semantic chunk exceeds the model's
           token budget — semantic boundaries don't guarantee token count.

    Args:
        text:          The full text to split.
        tokenizer:     From EmbeddingModelConfig.tokenizer — used for token limit check.
        max_tokens:    From EmbeddingModelConfig.max_tokens — used for token limit check.
        threshold:     Cosine similarity cutoff (0.0–1.0).
                       Lower = more chunks. Higher = fewer, larger chunks.
        min_sentences: Minimum sentences before a chunk boundary is allowed.

    Returns a list of text chunk strings, all within max_tokens.
    """
    # Split into sentences on common punctuation
    sentences = re.split(r'(?<=[.!?؟])\s+', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    if len(sentences) <= min_sentences:
        return [text]  # too short to bother splitting

    # MiniLM used for boundary detection only — fast and accurate enough.
    # The actual RAG embedding uses whichever model the user picked.
    embed_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
    embeddings  = embed_model.encode(sentences, show_progress_bar=False)

    chunks        = []
    current_chunk = [sentences[0]]

    for i in range(1, len(sentences)):
        # Compare current sentence embedding to the previous one
        sim = cosine_similarity(
            embeddings[i - 1].reshape(1, -1),
            embeddings[i].reshape(1, -1)
        )[0][0]

        # Low similarity = topic shift = start a new chunk
        # But respect min_sentences to avoid micro-chunks
        if sim < threshold and len(current_chunk) >= min_sentences:
            chunks.append(" ".join(current_chunk))
            current_chunk = [sentences[i]]
        else:
            current_chunk.append(sentences[i])

    # Flush the last chunk
    if current_chunk:
        chunks.append(" ".join(current_chunk))

    # Semantic boundaries don't guarantee token count — enforce the model's limit
    return enforce_token_limit(chunks, tokenizer, max_tokens)


# ─────────────────────────────────────────────
# CHUNKING — STRATEGY 4
# Document-structure chunking
# ─────────────────────────────────────────────

def split_text_by_structure(text: str, tokenizer, max_tokens: int) -> list[str]:
    """
    Split text using document structure signals (headings, section breaks).

    How it works:
        1. Detect structural boundaries: headings (short ALL-CAPS or numbered lines),
           double newlines (paragraph breaks), horizontal rules.
        2. Accumulate lines into a section until a boundary is hit.
        3. enforce_token_limit() splits any oversized sections using the model's
           actual tokenizer — more accurate than word counting.

    Args:
        text:       The full text to split.
        tokenizer:  From EmbeddingModelConfig.tokenizer — used for token limit check.
        max_tokens: From EmbeddingModelConfig.max_tokens — used for token limit check.

    Returns a list of text chunk strings, all within max_tokens.
    """
    # Patterns that signal a new section is starting
    heading_pattern = re.compile(
        r'^(\d+[\.\)]\s+\w)'           # numbered: "1. Introduction" or "2) Scope"
        r'|^([A-Z][A-Z\s]{4,})$'       # ALL CAPS heading: "BACKGROUND", "DEFINITIONS"
        r'|^(#{1,3}\s)'                 # markdown-style: "## Section"
        r'|^(={3,}|-{3,})$',           # horizontal rule: "===" or "---"
        re.MULTILINE
    )

    lines    = text.split('\n')
    sections = []
    current  = []

    for line in lines:
        stripped = line.strip()

        is_heading       = bool(heading_pattern.match(stripped))
        is_blank         = stripped == ''
        is_section_break = is_heading or (is_blank and len(current) > 2)

        if is_section_break and current:
            sections.append('\n'.join(current).strip())
            current = []

        if stripped:  # skip blank lines themselves, keep content
            current.append(stripped)

    # Flush the last section
    if current:
        sections.append('\n'.join(current).strip())

    # Filter empty sections then enforce the model's token limit
    sections = [s for s in sections if s.strip()]
    return enforce_token_limit(sections, tokenizer, max_tokens)


# ─────────────────────────────────────────────
# PDF EXTRACTION
# ─────────────────────────────────────────────

def extract_text_from_page(page) -> tuple[str, str]:
    """
    Extract and process text from a single PDF page.

    Handles both Arabic and English content, including mixed-language pages.
    Uses sentence-level language detection to reshape only Arabic sentences.

    Returns a tuple of:
        - processed text (str)
        - dominant language code (str), e.g. 'ar' or 'en'
    """
    raw_text = page.get_text()

    # Skip pages with no extractable text (e.g. scanned image pages)
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
    model_key:  str   = 'all-MiniLM-L6-v2',  # key from EMBEDDING_MODELS
    strategy:   str   = 'simple',             # simple | large | semantic | structure
    chunk_size: int   = 100,                  # [simple] words per chunk
    overlap:    int   = 10,                   # [simple] overlapping words
    threshold:  float = 0.5,                  # [semantic] cosine similarity cutoff
) -> list[dict]:
    """
    Full pipeline: extract text from a PDF and split into chunks for RAG.

    Tokenizer and max_tokens are resolved automatically from model_key —
    no need to pass them manually.

    For each page:
        1. Extract raw text using PyMuPDF
        2. Fix Arabic character shaping (if needed)
        3. Clean up whitespace
        4. Split using the chosen strategy with the correct tokenizer
        5. Store each chunk with its metadata

    Args:
        file_path:  Path to the PDF file.
        model_key:  Key from EMBEDDING_MODELS. Determines which tokenizer
                    and max_tokens to use. One of:
                        'all-MiniLM-L6-v2'     (256 tokens, BERT tokenizer)
                        'all-mpnet-base-v2'    (384 tokens, BERT tokenizer)
                        'intfloat/e5-large-v2' (512 tokens, BERT tokenizer)
                        'BAAI/bge-m3'          (512 tokens, BGE  tokenizer)
        strategy:   Chunking strategy. One of:
                        'simple'    — word-based overlap (fast, no tokenizer needed)
                        'large'     — token-aware large overlap
                        'semantic'  — topic-boundary detection
                        'structure' — heading/section-aware splitting
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
    # Resolve tokenizer and max_tokens from config — no manual passing needed
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

        # Skip pages that are empty after cleaning
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

        else:
            raise ValueError(f"Unknown strategy '{strategy}'. Choose: simple, large, semantic, structure")

        # ── Store chunks with metadata ────────────────────────
        for chunk_index, chunk_text in enumerate(page_chunks):
            if not chunk_text.strip():
                continue
            all_chunks.append({
                "text": chunk_text,
                "metadata": {
                    "source":      file_path,
                    "page":        page_number + 1,  # convert to 1-based page numbering
                    "language":    dominant_language,
                    "chunk_index": chunk_index,       # 0-based index within the page
                    "strategy":    strategy,
                    "model":       model_key,         # which embedding model this chunk is for
                    "token_limit": max_tokens,        # max tokens enforced for this model
                }
            })

    pdf_document.close()
    return all_chunks


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":

    FILE = "singapore-court-case1.pdf"

    # ── Strategy 1: simple — no tokenizer needed ────────────
    chunks_simple = parse_pdf_into_chunks(
        FILE, model_key='all-MiniLM-L6-v2', strategy='simple', chunk_size=100, overlap=10
    )
    print(f"[simple / MiniLM]     Total chunks: {len(chunks_simple)}")

    # ── Strategy 2: large overlap — BGE tokenizer, 512 tokens ─
    chunks_large = parse_pdf_into_chunks(
        FILE, model_key='BAAI/bge-m3', strategy='large'
    )
    print(f"[large / BGE-M3]      Total chunks: {len(chunks_large)}")

    # ── Strategy 3: semantic — BERT tokenizer, 384 tokens ───
    chunks_semantic = parse_pdf_into_chunks(
        FILE, model_key='all-mpnet-base-v2', strategy='semantic', threshold=0.5
    )
    print(f"[semantic / MPNet]    Total chunks: {len(chunks_semantic)}")

    # ── Strategy 4: structure — BERT tokenizer, 512 tokens ──
    chunks_structure = parse_pdf_into_chunks(
        FILE, model_key='intfloat/e5-large-v2', strategy='structure'
    )
    print(f"[structure / E5]      Total chunks: {len(chunks_structure)}")

    # ── Preview first 3 chunks ───────────────────────────────
    print("\n── Preview (semantic / MPNet) ──────────────────────")
    for chunk in chunks_semantic[:3]:
        m = chunk['metadata']
        print(f"Page {m['page']} | Lang: {m['language']} | Model: {m['model']} | Limit: {m['token_limit']} tokens")
        print(chunk["text"])
        print("─" * 50)