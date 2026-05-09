import os
import json
import logging

from django.shortcuts import get_object_or_404, render
from django.http import JsonResponse
from django.conf import settings

from .models import Document
from .services import parsing_service
from .services.embedding_service import EmbeddingService
from .services.model_selector import ModelSelector
from .services.qdrant_service import QdrantService
from workspace.models import Workspace

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = frozenset(
    {'.pdf', '.txt', '.csv', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx'}
)
MAX_FILE_SIZE_MB = 50


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _validate_uploaded_file(uploaded_file) -> tuple[bool, str | None]:
    """Returns (is_valid, error_message)."""
    _, ext = os.path.splitext(uploaded_file.name)
    ext = ext.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False, (
            f"'{uploaded_file.name}': file type '{ext}' is not supported. "
            f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    max_bytes = MAX_FILE_SIZE_MB * 1024 * 1024
    if uploaded_file.size > max_bytes:
        return False, (
            f"'{uploaded_file.name}' exceeds the {MAX_FILE_SIZE_MB} MB size limit "
            f"({uploaded_file.size // (1024 * 1024)} MB)."
        )
    return True, None


def _get_qdrant() -> QdrantService:
    return QdrantService(
        host=getattr(settings, 'QDRANT_HOST', 'localhost'),
        port=getattr(settings, 'QDRANT_PORT', 6333),
    )


def _require_config(workspace) -> tuple:
    """
    Returns (config, None) if the workspace has a config,
    or (None, JsonResponse) with a 400 error if it does not.
    """
    if not hasattr(workspace, 'config'):
        return None, JsonResponse(
            {"error": "This workspace has no configuration yet. Complete the questionnaire first."},
            status=400,
        )
    return workspace.config, None


# ─── Views ───────────────────────────────────────────────────────────────────

def documents_page(request, workspace_id):
    workspace = get_object_or_404(Workspace, workspace_id=workspace_id)
    documents = Document.objects.filter(workspace=workspace).order_by("-upload_time")
    return render(request, "documents/Documents.html", {
        "workspace":      workspace,
        "documents":      documents,
        "document_count": documents.count(),
    })


def text_input_page(request, workspace_id):
    workspace = get_object_or_404(Workspace, workspace_id=workspace_id)
    return render(request, "documents/text_input.html", {"workspace": workspace})


def save_file(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)

    workspace_id = request.POST.get("workspace_id")
    if not workspace_id:
        return JsonResponse({"error": "No workspace_id provided"}, status=400)

    uploaded_files = request.FILES.getlist("file") or request.FILES.getlist("files")
    if not uploaded_files:
        return JsonResponse({"error": "No files uploaded"}, status=400)

    workspace = get_object_or_404(Workspace, workspace_id=workspace_id)

    config, err = _require_config(workspace)
    if err:
        return err

    for uploaded_file in uploaded_files:
        valid, error = _validate_uploaded_file(uploaded_file)
        if not valid:
            return JsonResponse({"error": error}, status=400)

    model_config    = ModelSelector.get_model_config(config.embedding_model)
    qdrant          = _get_qdrant()
    collection_name = qdrant.ensure_collection(model_config)

    results = []
    for uploaded_file in uploaded_files:
        _, ext = os.path.splitext(uploaded_file.name)
        file_type = ext.lower().lstrip('.')

        doc = Document(
            document_title=uploaded_file.name,
            workspace=workspace,
            uploaded_by=request.user if request.user.is_authenticated else None,
        )
        doc.file = uploaded_file
        doc.save()

        doc_metadata = {
            "document_id":    doc.id,
            "document_title": doc.document_title,
            "workspace_id":   workspace.workspace_id,
            "uploaded_by":    request.user.username if request.user.is_authenticated else "anonymous",
            "upload_time":    doc.upload_time.isoformat(),
            "file_type":      file_type,
        }

        all_chunks = parsing_service.parse_document_into_chunks(
            file_path    = doc.file.path,
            model_key    = model_config.collection_key,
            strategy     = config.chunking_strategy or 'fixed-length',
            doc_metadata = doc_metadata,
        )

        for chunk in all_chunks:
            text     = chunk["text"]
            metadata = chunk["metadata"]

            vector = EmbeddingService.embed_text(
                text=text,
                model_name=model_config.model_name,
            )

            qdrant.index_document_chunk(
                collection_name=collection_name,
                workspace_id=workspace.workspace_id,
                document_id=doc.id,
                chunk_id=metadata['chunk_index'],
                text=text,
                vector=vector,
                additional_metadata={
                    k: metadata.get(k)
                    for k in ('section', 'language', 'source', 'document_title',
                              'uploaded_by', 'upload_time', 'file_type')
                },
            )

        results.append({
            "document_id": doc.id,
            "filename":    uploaded_file.name,
            "chunks":      len(all_chunks),
        })
        logger.info(
            f"Indexed {len(all_chunks)} chunks for '{uploaded_file.name}' "
            f"in workspace {workspace_id}"
        )

    if len(results) == 1:
        return JsonResponse({
            "message":     "Uploaded and indexed successfully",
            "document_id": results[0]["document_id"],
            "chunks":      results[0]["chunks"],
        })

    return JsonResponse({
        "message":   f"{len(results)} files uploaded and indexed successfully",
        "documents": results,
    })


def index_document_chunk(request):
    """Manually index a pre-chunked document chunk into Qdrant."""
    if request.method != 'POST':
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    workspace_id = data.get('workspace_id')
    document_id  = data.get('document_id')
    chunk_id     = data.get('chunk_id')
    text         = data.get('text')

    if not all([workspace_id, document_id is not None, chunk_id is not None, text]):
        return JsonResponse({
            "error": "Missing required fields: workspace_id, document_id, chunk_id, text"
        }, status=400)

    try:
        workspace = Workspace.objects.get(workspace_id=workspace_id)
    except Workspace.DoesNotExist:
        return JsonResponse({"error": f"Workspace {workspace_id} not found"}, status=404)

    config, err = _require_config(workspace)
    if err:
        return err

    try:
        model_config    = ModelSelector.get_model_config(config.embedding_model)
        qdrant          = _get_qdrant()
        collection_name = qdrant.ensure_collection(model_config)

        vector = EmbeddingService.embed_text(text=text, model_name=model_config.model_name)

        point_id = qdrant.index_document_chunk(
            collection_name=collection_name,
            workspace_id=workspace_id,
            document_id=document_id,
            chunk_id=chunk_id,
            text=text,
            vector=vector,
            additional_metadata=data.get('metadata', {}),
        )

        logger.info(f"Indexed chunk {chunk_id} of doc {document_id} for workspace {workspace_id}")

        return JsonResponse({
            'status':     'success',
            'point_id':   point_id,
            'collection': collection_name,
            'model':      model_config.model_name,
            'dimension':  model_config.dimension,
        }, status=201)

    except Exception as e:
        logger.error(f"Indexing error: {str(e)}", exc_info=True)
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


def search_documents(request):
    """Semantic search over a workspace's indexed documents."""
    if request.method != 'POST':
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    workspace_id    = data.get('workspace_id')
    query           = data.get('query')
    score_threshold = data.get('score_threshold')

    if not all([workspace_id, query]):
        return JsonResponse({"error": "Missing required fields: workspace_id, query"}, status=400)

    try:
        workspace = Workspace.objects.get(workspace_id=workspace_id)
    except Workspace.DoesNotExist:
        return JsonResponse({"error": f"Workspace {workspace_id} not found"}, status=404)

    config, err = _require_config(workspace)
    if err:
        return err

    try:
        model_config    = ModelSelector.get_model_config(config.embedding_model)
        qdrant          = _get_qdrant()
        collection_name = ModelSelector.get_collection_name(model_config.collection_key)

        query_vector = EmbeddingService.embed_text(text=query, model_name=model_config.model_name)

        results = qdrant.search(
            collection_name=collection_name,
            workspace_id=workspace_id,
            query_vector=query_vector,
            top_k=config.top_k,
            score_threshold=score_threshold,
        )

        formatted_results = [
            {
                'id':          r['id'],
                'score':       r['score'],
                'document_id': r['payload']['document_id'],
                'chunk_id':    r['payload']['chunk_id'],
                'text':        r['payload']['text'],
                'metadata': {
                    k: v for k, v in r['payload'].items()
                    if k not in {'workspace_id', 'document_id', 'chunk_id', 'text'}
                },
            }
            for r in results
        ]

        logger.info(f"Search returned {len(formatted_results)} results for workspace {workspace_id}")

        return JsonResponse({
            'status':        'success',
            'query':         query,
            'model':         model_config.model_name,
            'results':       formatted_results,
            'total_results': len(formatted_results),
        })

    except Exception as e:
        logger.error(f"Search error: {str(e)}", exc_info=True)
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


def delete_document(request):
    """Delete all Qdrant chunks and the DB record for a document."""
    if request.method != 'POST':
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    workspace_id = data.get('workspace_id')
    document_id  = data.get('document_id')

    if not workspace_id or document_id is None:
        return JsonResponse({"error": "workspace_id and document_id are required"}, status=400)

    try:
        workspace_id = int(workspace_id)
        workspace    = Workspace.objects.get(workspace_id=workspace_id)
    except (ValueError, Workspace.DoesNotExist):
        return JsonResponse({"error": f"Invalid workspace_id: {workspace_id}"}, status=404)

    try:
        document_id = int(document_id)
    except (ValueError, TypeError):
        return JsonResponse({"error": "document_id must be an integer"}, status=400)

    config, err = _require_config(workspace)
    if err:
        return err

    try:
        model_config    = ModelSelector.get_model_config(config.embedding_model)
        qdrant          = _get_qdrant()
        collection_name = ModelSelector.get_collection_name(model_config.collection_key)

        deleted_count = qdrant.delete_document(
            collection_name=collection_name,
            workspace_id=workspace_id,
            document_id=document_id,
        )

        Document.objects.filter(id=document_id, workspace=workspace).delete()
        logger.info(f"Deleted document {document_id} from workspace {workspace_id}")

        return JsonResponse({
            'status':         'success',
            'document_id':    document_id,
            'deleted_chunks': str(deleted_count),
        })

    except Exception as e:
        logger.error(f"Delete error: {str(e)}", exc_info=True)
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
