from django.shortcuts import get_object_or_404, render
from django.http import JsonResponse
from django.conf import settings
import json
import logging

from .models import Document
from .services import parsing_service
from .services.embedding_service import EmbeddingService
from .services.model_selector import ModelSelector
from .services.qdrant_service import QdrantService

from workspace.models import Workspace
import time

logger = logging.getLogger(__name__)


def documents_page(request):
    """
    Render the documents page.
    Workspace is resolved from (in priority order):
      1. ?workspace_id=<id> query param
      2. request.session['workspace_id']
    """
    workspace_id = request.GET.get("workspace_id") or request.session.get("workspace_id")
    workspace = None

    if workspace_id:
        try:
            #print(f'here is the workspaceID {workspace_id}')
            workspace = Workspace.objects.get(workspace_id=workspace_id)
            # Keep it in session so subsequent requests don't need the query param
            request.session["workspace_id"] = workspace.workspace_id
        except Workspace.DoesNotExist:
            pass

    # If still no workspace, fall back to the first workspace for this user
    if workspace is None and request.user.is_authenticated:
        workspace = Workspace.objects.filter().first()  # adjust filter as needed
        if workspace:
            request.session["workspace_id"] = workspace.workspace_id

    documents = Document.objects.filter(workspace=workspace).order_by("-upload_time") if workspace else []

    document_count = len(documents)

    return render(request, "documents/Documents.html", {
        "workspace": workspace,
        "documents": documents,
        "document_count": document_count,
    })


def text_input_page(request):
    workspace_id = request.GET.get("workspace_id") or request.session.get("workspace_id")
    workspace = None

    if workspace_id:
        try:
            workspace = Workspace.objects.get(workspace_id=workspace_id)
        except Workspace.DoesNotExist:
            pass

    return render(request, "documents/text_input.html", {
        "workspace": workspace,
    })


def save_file(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)

    pdf_file = request.FILES.get("file")
    workspace_id = request.POST.get("workspace_id")

    if not pdf_file:
        return JsonResponse({"error": "No file uploaded"}, status=400)

    if not workspace_id:
        return JsonResponse({"error": "No workspace_id"}, status=400)

    workspace = get_object_or_404(Workspace, workspace_id=workspace_id)

    # --- Qdrant setup ---
    workspace_embedding_model = workspace.config.embedding_model
    model_config = ModelSelector.get_model_config(workspace_embedding_model)

    qdrant = QdrantService(
        host=getattr(settings, 'QDRANT_HOST', 'localhost'),
        port=getattr(settings, 'QDRANT_PORT', 6333)
    )
    collection_name = qdrant.ensure_collection(model_config)

    # --- Save document ---
    doc = Document(
        document_title=pdf_file.name,
        workspace=workspace,
        uploaded_by=request.user if request.user.is_authenticated else None,
    )
    doc.file = pdf_file
    doc.save()

    # --- Parse uploaded file ---
    all_chunks = parsing_service.parse_pdf_into_chunks(doc.file.path)

    # --- Embed and index chunks ---
    for chunk in all_chunks:
        text = chunk["text"]
        metadata = chunk["metadata"]

        vector = EmbeddingService.embed_text(
            text=text,
            model_name=model_config.model_name
        )

        qdrant.index_document_chunk(
            collection_name=collection_name,
            workspace_id=workspace.workspace_id,
            document_id=doc.id,
            chunk_id=metadata['chunk_index'],
            text=text,
            vector=vector,
            additional_metadata={
                "page": metadata['page'],
                "language": metadata['language'],
            }
        )

    return JsonResponse({"message": "Uploaded and indexed successfully", "document_id": doc.id})


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

def delete_document(request, document_id):
    """
    Delete all chunks of a document from Qdrant.
    
    DELETE /api/documents/<document_id>/?workspace_id=1
    
    Response:
    {
        "status": "success",
        "document_id": 123,
        "deleted_chunks": 5
    }
    """
    if request.method != 'DELETE':
        return JsonResponse({"error": "Only DELETE allowed"}, status=405)
    
    # Get workspace_id from query params
    workspace_id = request.GET.get('workspace_id')
    if not workspace_id:
        return JsonResponse({"error": "workspace_id query param is required"}, status=400)
    
    try:
        workspace_id = int(workspace_id)
        workspace = Workspace.objects.get(workspace_id=workspace_id)
    except (ValueError, Workspace.DoesNotExist):
        return JsonResponse({"error": f"Invalid workspace_id: {workspace_id}"}, status=404)
    
    try:
        document_id = int(document_id)
    except ValueError:
        return JsonResponse({"error": "document_id must be an integer"}, status=400)
    
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
        
        # Delete with workspace isolation
        deleted_count = qdrant.delete_document(
            collection_name=collection_name,
            workspace_id=workspace_id,
            document_id=document_id,
        )
        
        logger.info(f" Deleted document {document_id} from workspace {workspace_id}")
        
        return JsonResponse({
            'status': 'success',
            'document_id': document_id,
            'deleted_chunks': deleted_count,
        }, status=200)
        
    except Exception as e:
        logger.error(f"❌ Delete error: {str(e)}", exc_info=True)
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)



def fixed_chunking(sentences: list[str], chunk_size: int, overlap: int = 0) -> list[str]: #for now this its place 
    """
    Split sentences into fixed-size chunks with optional overlap.
    Returns a list of text chunks ready for embedding.
    """

    # Return empty list if no input
    if not sentences:
        return []

    # Validate parameters
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >= 0 and < chunk_size")

    chunks = []
    step = chunk_size - overlap  # how much we move forward each iteration
    i = 0

    # Slide over sentences using fixed window
    while i < len(sentences):
        chunk = sentences[i:i + chunk_size]   # take chunk_size sentences
        chunks.append(" ".join(chunk))        # merge into single string
        i += step                             # move window forward

    return chunks         