python# Simple example showing how 3 services work together

from documents.services import ModelSelector, EmbeddingService, QdrantService

# ============================================
# STEP 1: Model Selection
# ============================================
print("Step 1: Figure out which model to use")

# Your questionnaire saved this in WorkspaceConfig:
workspace_embedding_model = "all-mpnet-base-v2"

# ModelSelector translates it:
model_config = ModelSelector.get_model_config(workspace_embedding_model)

print(f"✅ Model: {model_config.model_name}")
print(f"✅ Dimension: {model_config.dimension}")
print(f"✅ Collection: {model_config.collection_key}")
# Output:
# ✅ Model: sentence-transformers/all-mpnet-base-v2
# ✅ Dimension: 768
# ✅ Collection: mpnet

# ============================================
# STEP 2: Text → Vector (Embedding)
# ============================================
print("\nStep 2: Convert text to vector")

text = "Django is a high-level Python web framework"

# EmbeddingService converts text to numbers:
vector = EmbeddingService.embed_text(
    text=text,
    model_name=model_config.model_name
)

print(f"✅ Text: {text}")
print(f"✅ Vector: [{vector[0]:.3f}, {vector[1]:.3f}, {vector[2]:.3f}, ...] (768 numbers)")
# Output:
# ✅ Text: Django is a high-level Python web framework
# ✅ Vector: [0.123, -0.456, 0.789, ...] (768 numbers)

# ============================================
# STEP 3: Save to Qdrant
# ============================================
print("\nStep 3: Save vector to Qdrant")

# Connect to Qdrant:
qdrant = QdrantService(host="localhost", port=6333)

# Create collection if needed:
collection_name = qdrant.ensure_collection(model_config)
print(f"✅ Collection ready: {collection_name}")

# Save the vector:
point_id = qdrant.index_document_chunk(
    collection_name=collection_name,
    workspace_id=1,          # Workspace isolation
    document_id=123,         # Which document
    chunk_id=0,              # Which chunk
    text=text,               # Original text
    vector=vector,           # The 768 numbers
    additional_metadata={"title": "Django Docs", "page": 1}
)

print(f"✅ Saved! Point ID: {point_id}")
# Output:
# ✅ Saved! Point ID: abc-123-uuid

# ============================================
# STEP 4: Search (Example)
# ============================================
print("\nStep 4: Search for similar text")

query = "What is Django?"

# Convert query to vector:
query_vector = EmbeddingService.embed_text(
    text=query,
    model_name=model_config.model_name
)

# Search Qdrant:
results = qdrant.search(
    collection_name=collection_name,
    workspace_id=1,          # Only search workspace 1
    query_vector=query_vector,
    top_k=5
)

print(f"✅ Found {len(results)} results")
for i, result in enumerate(results):
    print(f"  {i+1}. Score: {result['score']:.2f} - {result['payload']['text'][:50]}...")
# Output:
# ✅ Found 1 results
#   1. Score: 0.92 - Django is a high-level Python web framework...