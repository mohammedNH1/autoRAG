from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import json
import logging
from workspace.models import Workspace
from .services import EmbeddingService, QdrantService, ModelSelector#(Classes from documents/services )

"""
Qdrant- Document Indexing(storing) and Search

RESPONSIBILITY:
- POST /api/documents/index/   - Save chunks to Qdrant
- POST /api/documents/search/  - Search Qdrant
"""

logger = logging.getLogger(__name__)


@csrf_exempt
def index_document_chunk(request):
    """
    Index(store) a pre-chunked document chunk into Qdrant.
    
    POST /api/documents/index/
    {
        "workspace_id": 1,
        "document_id": 123,
        "chunk_id": 0,
        "text": "This is a chunk of text...",
        "metadata": {"title": "My Doc", "page": 1}
    }
    Response:
    {
        "status": "success",
        "point_id": "uuid-string",
        "collection": "documents__mpnet",
        "model": "sentence-transformers/all-mpnet-base-v2",
        "dimension": 768
    }
    """
    if request.method != 'POST':
        return JsonResponse({"error": "Only POST allowed"}, status=405)
    
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    
    # Validate required fields
    workspace_id = data.get('workspace_id')
    document_id = data.get('document_id')
    chunk_id = data.get('chunk_id')
    text = data.get('text')
    
    if not all([workspace_id, document_id is not None, chunk_id is not None, text]):
        return JsonResponse({
            "error": "Missing required fields: workspace_id, document_id, chunk_id, text"
        }, status=400)
    
    try:
        # Get workspace
        workspace = Workspace.objects.get(workspace_id=workspace_id)
    except Workspace.DoesNotExist:
        return JsonResponse({"error": f"Workspace {workspace_id} not found"}, status=404)
    
    try:
        # Get workspace's embedding model from config
        config = workspace.config
        embedding_model_name = config.embedding_model
        
        # Get model configuration
        model_config = ModelSelector.get_model_config(embedding_model_name)
        
        # Initialize Qdrant
        qdrant = QdrantService(
            host=getattr(settings, 'QDRANT_HOST', 'localhost'),
            port=getattr(settings, 'QDRANT_PORT', 6333)
        )
        
        # Ensure collection exists with correct dimension
        collection_name = qdrant.ensure_collection(model_config)
        
        # Convert text to vector (REAL embeddings!)
        vector = EmbeddingService.embed_text(
            text=text,
            model_name=model_config.model_name
        )
        
        # Save to Qdrant with workspace isolation
        point_id = qdrant.index_document_chunk(
            collection_name=collection_name,
            workspace_id=workspace_id,
            document_id=document_id,
            chunk_id=chunk_id,
            text=text,
            vector=vector,
            additional_metadata=data.get('metadata', {}),
        )
        
        logger.info(f" Indexed chunk {chunk_id} of doc {document_id} for workspace {workspace_id}")
        
        return JsonResponse({
            'status': 'success',
            'point_id': point_id,
            'collection': collection_name,
            'model': model_config.model_name,
            'dimension': model_config.dimension,
        }, status=201)
        
    except Exception as e:
        logger.error(f"❌ Indexing error: {str(e)}", exc_info=True)
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


@csrf_exempt
def search_documents(request):
    """
    Search for similar documents using semantic search.
    
     return raw search results - After this is re-ranking and LLM.
    
    POST /api/documents/search/
    {
        "workspace_id": 1,
        "query": "What is the admission policy?",
        "top_k": 5,
        "score_threshold": 0.7  // optional
    }
    
    Response:
    {
        "status": "success",
        "query": "What is...",
        "model": "sentence-transformers/all-mpnet-base-v2",
        "results": [
            {
                "id": "uuid",
                "score": 0.92,
                "document_id": 123,
                "chunk_id": 0,
                "text": "...",
                "metadata": {...}
            }
        ],
        "total_results": 5
    }
    """
    if request.method != 'POST':
        return JsonResponse({"error": "Only POST allowed"}, status=405)
    
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    
    # Validate required fields
    workspace_id = data.get('workspace_id')
    query = data.get('query')
    
    if not all([workspace_id, query]):
        return JsonResponse({
            "error": "Missing required fields: workspace_id, query"
        }, status=400)
    
    top_k = data.get('top_k', 5)
    score_threshold = data.get('score_threshold')
    
    try:
        # Get workspace
        workspace = Workspace.objects.get(workspace_id=workspace_id)
    except Workspace.DoesNotExist:
        return JsonResponse({"error": f"Workspace {workspace_id} not found"}, status=404)
    
    try:
        # Get workspace's embedding model
        config = workspace.config
        embedding_model_name = config.embedding_model
        
        # Get model configuration
        model_config = ModelSelector.get_model_config(embedding_model_name)
        
        # Initialize Qdrant
        qdrant = QdrantService(
            host=getattr(settings, 'QDRANT_HOST', 'localhost'),
            port=getattr(settings, 'QDRANT_PORT', 6333)
        )
        
        collection_name = ModelSelector.get_collection_name(model_config.collection_key)
        
        # Convert query to vector (REAL embeddings!)
        query_vector = EmbeddingService.embed_text(
            text=query,
            model_name=model_config.model_name
        )
        
        # Search Qdrant with workspace isolation
        results = qdrant.search(
            collection_name=collection_name,
            workspace_id=workspace_id,
            query_vector=query_vector,
            top_k=top_k,
            score_threshold=score_threshold,
        )
        
        # Format results
        formatted_results = []
        for result in results:
            formatted_results.append({
                'id': result['id'],
                'score': result['score'],
                'document_id': result['payload']['document_id'],
                'chunk_id': result['payload']['chunk_id'],
                'text': result['payload']['text'],
                'metadata': {
                    k: v for k, v in result['payload'].items()
                    if k not in ['workspace_id', 'document_id', 'chunk_id', 'text']
                }
            })
        
        logger.info(f" Search returned {len(formatted_results)} results for workspace {workspace_id}")
        
        return JsonResponse({
            'status': 'success',
            'query': query,
            'model': model_config.model_name,
            'results': formatted_results,
            'total_results': len(formatted_results),
        }, status=200)
        
    except Exception as e:
        logger.error(f" Search error: {str(e)}", exc_info=True)
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)