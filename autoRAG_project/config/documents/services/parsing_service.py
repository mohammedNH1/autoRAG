import fitz                  # PyMuPDF - for reading PDF files
import re                    # for text cleaning and splitting
from langdetect import detect # for detecting language of text
import arabic_reshaper        # for fixing Arabic character shapes for NLP/embedding

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
        return "en" # default to English if detection fails


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
# CHUNKING
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
        chunk_words = words[start_index : start_index + chunk_size]
        chunk = " ".join(chunk_words)
        chunks.append(chunk)

    return chunks


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

    processed_text = process_mixed_language_text(raw_text)
    dominant_language = detect_dominant_language(processed_text)

    return processed_text, dominant_language


def parse_pdf_into_chunks(file_path: str, chunk_size: int = 100, overlap: int = 10) -> list[dict]:
    """
    Full pipeline: extract text from a PDF and split it into chunks for RAG.

    For each page:
        1. Extract raw text using PyMuPDF
        2. Fix Arabic character shaping (if needed)
        3. Clean up whitespace
        4. Split into overlapping chunks
        5. Store each chunk with its metadata

    Args:
        file_path:  Path to the PDF file.
        chunk_size: Number of words per chunk (default: 100).
        overlap:    Number of overlapping words between chunks (default: 10).

    Returns a list of dicts, each containing:
        {
            "text":     the chunk text,
            "metadata": {
                "source":       the PDF file path,
                "page":         page number (1-based),
                "language":     dominant language of the page ('ar' or 'en'),
                "chunk_index":  index of the chunk within the page (0-based)
            }
        }
    """
    pdf_document = fitz.open(file_path)
    all_chunks = []

    for page_number, page in enumerate(pdf_document):
        page_text, dominant_language = extract_text_from_page(page)
        cleaned_text = clean_extracted_text(page_text)

        # Skip pages that are empty after cleaning
        if not cleaned_text:
            continue

        page_chunks = split_text_into_chunks(cleaned_text, chunk_size, overlap)

        for chunk_index, chunk_text in enumerate(page_chunks):
            all_chunks.append({
                "text": chunk_text,
                "metadata": {
                    "source":      file_path,
                    "page":        page_number + 1,  # convert to 1-based page numbering
                    "language":    dominant_language,
                    "chunk_index": chunk_index        # 0-based index within the page
                }
            })

    pdf_document.close()
    return all_chunks


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    all_chunks = parse_pdf_into_chunks("singapore-court-case1.pdf")

    print(f"Total chunks: {len(all_chunks)}")
    for chunk in all_chunks[:3]:  # preview first 3 chunks
        print(f"Page {chunk['metadata']['page']} | Lang: {chunk['metadata']['language']} | Chunk: {chunk['metadata']['chunk_index']}")
        print(chunk["text"])
        print("─" * 50)