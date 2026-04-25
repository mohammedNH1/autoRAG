import parsing_service
import fitz  # PyMuPDF

from pathlib import Path

PDF_FILE = Path(__file__).parent / "1706.03762v7.pdf"
MODEL_KEY = "minilm"
STRATEGY  = "hierarchical" # simple | large | semantic | structure | page | paragraph | hierarchical
PREVIEW   = 10


doc = fitz.open("/app/web/documents/services/1706.03762v7.pdf")
page = doc[0]
raw = page.get_text()
print(repr(raw[:500]))  # show exact characters including \n
doc.close()

def test_chunking(pdf_file, model_key, strategy, preview):
    print(f"\n{'─' * 50}")
    print(f"  PDF:      {pdf_file}")
    print(f"  Model:    {model_key}")
    print(f"  Strategy: {strategy}")
    print(f"{'─' * 50}\n")

    try:
        chunks = parsing_service.parse_pdf_into_chunks(
            file_path = pdf_file,
            model_key = model_key,
            strategy  = strategy,
        )
    except Exception as e:
        print(f"ERROR: {e}")
        return

    print(f"Total chunks: {len(chunks)}\n")

    for i, chunk in enumerate(chunks[:preview]):
        m = chunk['metadata']
        print(chunk)
        print(f"{chunk['text'][:300]}")
        print(f"{'─' * 50}")

# call directly — no guard
test_chunking(PDF_FILE, MODEL_KEY, STRATEGY, PREVIEW)