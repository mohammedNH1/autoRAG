from qdrant_service import QdrantService
from embedding_service import EmbeddingService
from model_selector import ModelSelector
import parsing_service


# =========================
# Setup
# =========================
workspace_embedding_model = "all-mpnet-base-v2"
model_config = ModelSelector.get_model_config(workspace_embedding_model)

qdrant = QdrantService(host="qdrant_test", port=6333)
collection_name = qdrant.ensure_collection(model_config)

# =========================
# Parse PDF
# =========================
all_chunks = parsing_service.parse_pdf_into_chunks("singapore-court-case1.pdf")

# =========================
# Index chunks
# =========================
for i, chunk in enumerate(all_chunks[:21]):
    text = chunk["text"]

    vector = EmbeddingService.embed_text(
        text=text,
        model_name=model_config.model_name
    )

    point_id = qdrant.index_document_chunk(
        collection_name=collection_name,
        workspace_id=1,
        document_id=123,
        chunk_id=i,
        text=text,
        vector=vector,
        additional_metadata={"title": "Django Docs", "page": 1}
    )

    print(f"Saved chunk {i}")


# =========================
# 1. Count check
# =========================
count = qdrant.client.count(collection_name=collection_name)
print("\nTotal points in collection:", count)


# =========================
# 2. Scroll (retrieve sample)
# =========================
points, _ = qdrant.client.scroll(
    collection_name=collection_name,
    limit=5,
    with_vectors=True,
    with_payload=True
)

print("\nSample stored points:\n")

for p in points:
    print("ID:", p.id)
    print("Text:", p.payload.get("text")[:100])  # preview only
    print("Vector length:", len(p.vector))
    print("-----")


# =========================
# 3. Search 🔥 (using YOUR function)
# =========================
query_text = "Ltd v New Garage and Motor Company, Limited [1915] AC 79 (“Dunlop”): a liquidated damages clause is only enforceable if it is compensatory in nature, meaning that it provides a “genuine pre-estimate”"

query_vector = EmbeddingService.embed_text(
    text=query_text,
    model_name=model_config.model_name
)

results = qdrant.search(
    collection_name=collection_name,
    workspace_id=1,
    query_vector=query_vector,
    top_k=5,
    score_threshold=None   # خله None بالبداية
)

print("\nSearch Results:\n")

for i, r in enumerate(results):
    print(f"Result {i+1}")
    print("Score:", r["score"])
    print("Text:", r["payload"]["text"][:200])
    print("Document ID:", r["payload"]["document_id"])
    print("Chunk ID:", r["payload"]["chunk_id"])
    print("-----")
# qdrant.delete_document(
#     collection_name=collection_name,
#     workspace_id=1,
#     document_id=123
# )
