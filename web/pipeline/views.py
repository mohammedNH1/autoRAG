from django.shortcuts import render
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.db import transaction
import requests
from workspace.models import Workspace, WorkspaceConfig, WorkspaceMembership
from pipeline.services.pipeline_registry import get_pipeline
from pipeline.services.query_service import run_query, OLLAMA_URL, OLLAMA_MODEL
from workspace.models import Message, Session
import uuid
from django.core.exceptions import ValidationError
import datetime


REQUIRED_QUESTIONNAIRE_FIELDS = (
    "language", "use_case", "reference", "temperature", "top_p",
    "uptodate", "metadata", "chunking_strategy",
)

#Added by rayan to run here the questionnaire page
def questionnaire_page(request):
    """Backend logic here"""
    return render(request, "questionnaire.html")


@csrf_exempt
@login_required
def questionnaire(request):
    if request.method != 'POST':
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    content_type = (request.META.get('CONTENT_TYPE') or '').lower()
    image_file = None
    if content_type.startswith('multipart/form-data'):
        data = {k: v for k, v in request.POST.items()}
        image_file = request.FILES.get('workspace_image')
    else:
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

    # Reject early if any answer is missing — no workspace should be created
    # unless the questionnaire is fully and validly answered.
    missing = [f for f in REQUIRED_QUESTIONNAIRE_FIELDS if not data.get(f)]
    if missing:
        return JsonResponse(
            {"error": f"Missing answers: {', '.join(missing)}"}, status=400
        )

    workspace_id = data.get("workspace_id")
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()

    # When creating a brand-new workspace from the unified modal, the
    # name is required. When attaching a config to an existing workspace
    # (legacy /questionnaire/?workspace_id=X flow), the name is irrelevant.
    if not workspace_id:
        if not name:
            return JsonResponse({"error": "Workspace name is required"}, status=400)
        if len(name) > 150:
            return JsonResponse({"error": "Name must be 150 characters or fewer"}, status=400)
        if image_file is None:
            return JsonResponse({"error": "Workspace image is required"}, status=400)
        if not (image_file.content_type or '').startswith('image/'):
            return JsonResponse({"error": "Uploaded file must be an image"}, status=400)
        if image_file.size > 5 * 1024 * 1024:
            return JsonResponse({"error": "Image must be 5 MB or smaller"}, status=400)

    # Compute config values from raw answers.
    language          = data.get("language")
    use_case          = data.get("use_case")
    reference_value   = data.get("reference")
    temperature_value = data.get("temperature")
    top_p_value       = data.get("top_p")
    uptodate_value    = data.get("uptodate")
    metadata_value    = data.get("metadata")
    chunking_value    = data.get("chunking_strategy")

    embedding_config  = embedding_reranker(language, use_case)
    k_value           = top_k(reference_value)
    reference_flag    = reference(reference_value)
    temp_value        = temperature(temperature_value)
    top_p_final       = top_p(top_p_value)
    uptodate_flag     = up_to_date_docs(uptodate_value)
    metadata_flag     = add_metadata(metadata_value)
    chunking_strategy = determine_chunking_strategy(chunking_value)

    # Atomic: workspace + owner membership + config all succeed, or none persist.
    try:
        with transaction.atomic():
            if workspace_id:
                # Legacy path: attach config to an already-created workspace.
                # Only allow when the requesting user owns or is in the workspace.
                workspace = Workspace.objects.get(workspace_id=workspace_id)
                is_member = (
                    workspace.workspace_owner_id == request.user.id
                    or WorkspaceMembership.objects.filter(
                        workspace=workspace, user=request.user
                    ).exists()
                )
                if not is_member:
                    return JsonResponse({"error": "Forbidden"}, status=403)
            else:
                workspace = Workspace.objects.create(
                    workspace_name=name,
                    workspace_description=description,
                    workspace_owner=request.user,
                    workspace_image=image_file,
                )
                WorkspaceMembership.objects.create(
                    workspace=workspace,
                    user=request.user,
                    role="owner",
                )

            raw_answers = {
                f: data.get(f) for f in REQUIRED_QUESTIONNAIRE_FIELDS
            }

            WorkspaceConfig.objects.create(
                workspace=workspace,
                retrieval_type='none',
                re_ranker=embedding_config["reranker_model"],
                embedding_model=embedding_config["embedding_model"],
                chunking_strategy=chunking_strategy,
                distance_metric="cosine",
                temperature=temp_value,
                top_p=top_p_final,
                top_k=k_value,
                is_citation=reference_flag,
                metadata_flag=metadata_flag,
                raw_answers=raw_answers,
            )
    except Workspace.DoesNotExist:
        return JsonResponse({"error": "Workspace not found"}, status=404)

    return JsonResponse({
        "status": "success",
        "workspace_id": workspace.workspace_id,
        "config": {
            "embedding": embedding_config,
            "top_k": k_value,
            "reference": reference_flag,
            "temperature": temp_value,
            "top_p": top_p_final,
            "uptodate": uptodate_flag,
            "metadata": metadata_flag,
            "chunking_strategy": chunking_strategy,
        },
    })


"""
EXAMPLE of json(API) or (form) sent from frontend to backend (including the 9 answers) hi abdul:
{
    "reference": True,
    'temprature': 0.7,
    'top_p': 0.9,
    'upToDate': True,
    'chunking_strategy':'slide deck'
}

"""
def embedding_reranker(language, use_case):
   
    if language == 'english':
        if use_case == 'fast':
            return {
                "embedding_model": "all-MiniLM-L6-v2",
                "reranker_model": "cross-encoder/ms-marco-MiniLM-L6-v2"
            }

        elif use_case == 'balanced':
            return {
                "embedding_model": "all-mpnet-base-v2",
                "reranker_model": "cross-encoder/ms-marco-MiniLM-L6-v2"
            }

        elif use_case == 'quality':
            return {
                "embedding_model": "intfloat/e5-large-v2",
                "reranker_model": "intfloat/e5-mistral-7b-instruct"
            }
    else:
        return {
            "embedding_model": "BAAI/bge-m3",
            "reranker_model": "BAAI/bge-reranker-v2-m3"
        }


def top_k(top_k_value):  
    if top_k_value == 'main':
        k = 5
    else:
        k = 10
    return k

def temperature(temperature_value):
    temp = 0
    if temperature_value == 'precise':
        temp = 0.2
    elif temperature_value == 'balanced':
        temp = 0.5
    else: # creative
        temp = 0.8
    return temp      

def top_p(top_p_value):  
    top = 0
    if top_p_value == 'strict':
        top = 0.2
    elif top_p_value == 'balanced':
        top = 0.5
    else: # explaratory
        top = 0.9
    return top
        

def reference(reference_value):
    if reference_value == 'yes':
        return True
    else:
        return False
    
def up_to_date_docs(response):
    """
    Determines if the user wants the document up to date on not.
    """
    if response.lower().strip()== 'yes':
        uptodate = True
    else:
        uptodate = False

    return uptodate

def add_metadata(response):
    """
    Determines if the user wants the answer with metadata or not .
    """
    return str(response).lower().strip() == 'detailed'

def determine_chunking_strategy(response):
    """
    Determines the appropriate chunking strategy based on content type response. hi 

    """
    response_lower = response.lower().strip()

    if 'slide deck' in response_lower:
        chunking_strategy = 'page-based'

    elif 'meeting notes' in response_lower:
        chunking_strategy = 'large-overlapping'

    elif 'article' in response_lower:
        chunking_strategy = 'paragraph-based'

    elif 'manual' in response_lower:
        chunking_strategy = 'hierarchical'

    elif 'research paper' in response_lower:
        chunking_strategy = 'semantic'

    elif 'policy' in response_lower:
        chunking_strategy = 'document-structure'

    else:
        chunking_strategy = 'fixed-length'

    return chunking_strategy


def initiate_pipeline(request, workspace_id):
    workspace = Workspace.objects.get(workspace_id=workspace_id)
    config = workspace.config

    get_pipeline(workspace_id, config)

    return JsonResponse({"status": "Pipeline initialized"})

def chat_page(request, workspace_id):
    workspace = Workspace.objects.get(workspace_id=workspace_id)
    get_pipeline(workspace_id, workspace.config)
    return render(request, "chat.html", {"workspace_id": workspace_id})

@csrf_exempt
@login_required
def query_handling(request):
    print(f"[{datetime.datetime.now()}] PIPELINE START: Received query request")
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    workspace_id = int(data.get("workspace_id"))
    session_id = data.get("session_id")
    query = (data.get("message") or "").strip()

    if not workspace_id or not query:
        return JsonResponse(
            {'error': 'workspace_id and message are required'}, status=400
        )

    try:
        workspace = Workspace.objects.get(workspace_id=workspace_id)
    except Workspace.DoesNotExist:
        return JsonResponse({'error': 'Workspace not found'}, status=404)

    is_member = (
        workspace.workspace_owner_id == request.user.id
        or WorkspaceMembership.objects.filter(
            workspace=workspace, user=request.user
        ).exists()
    )
    if not is_member:
        return JsonResponse({'error': 'Forbidden'}, status=403)

    if not hasattr(workspace, 'config'):
        return JsonResponse(
            {'error': 'Workspace is not configured yet'}, status=400
        )

    # -------------------------
    # Session — must belong to this user + workspace; otherwise start a new one.
    # -------------------------
    session = None
    if session_id:
        try:
            session = Session.objects.filter(
                session_id=session_id,
                workspace=workspace,
                user=request.user,
            ).first()
        except (ValueError, ValidationError):
            session = None

    if not session:
        session = Session.objects.create(
            workspace=workspace,
            user=request.user,
            title="New Session",
        )

    is_first_message = not session.messages.exists()

    Message.objects.create(session=session, sender="user", text=query)

    # -------------------------
    # Run the shared RAG pipeline (also used by /api/v1/query)
    # -------------------------
    result = run_query(workspace, query)

    if result.no_documents:
        Message.objects.create(session=session, sender="assistant", text=result.answer)
        return JsonResponse({
            "response":       result.answer,
            "session_id":     str(session.session_id),
            "session_title":  session.title,
            "session_created": is_first_message,
        })

    llm_response  = result.answer
    sources       = result.sources
    is_citation   = result.is_citation
    metadata_flag = result.metadata_flag

    # -------------------------
    # Post-response appendix — grouped per document, not per chunk
    # -------------------------
    appendix_parts = []

    if sources:
        # Group chunks by document_id → collect pages and document-level fields
        _doc_level = {'document_id', 'document_title', 'uploaded_by', 'upload_time', 'file_type', 'source'}
        docs = {}  # document_id → {fields, pages[]}
        for s in sources:
            doc_id = s.get('document_id', s.get('document_title', 'unknown'))
            if doc_id not in docs:
                docs[doc_id] = {
                    'fields': {k: v for k, v in s.items() if k in _doc_level},
                    'pages':  [],
                }
            page = s.get('section') or s.get('page', '?')
            if page not in docs[doc_id]['pages']:
                docs[doc_id]['pages'].append(page)

        if is_citation:
            citation_lines = [
                f"- \"{d['fields'].get('document_title', 'Unknown')}\" — "
                f"Pages: {', '.join(str(p) for p in d['pages'])}"
                for d in docs.values()
            ]
            appendix_parts.append("**Sources:**\n" + "\n".join(citation_lines))

        if metadata_flag:
            meta_lines = []
            for i, d in enumerate(docs.values(), 1):
                f = d['fields']

                raw_time = f.get('upload_time', '')
                try:
                    upload_time = datetime.datetime.fromisoformat(raw_time).strftime('%d %b %Y, %H:%M')
                except (ValueError, TypeError):
                    upload_time = raw_time

                meta_lines.append(
                    f"[{i}] uploaded_by: {f.get('uploaded_by', '—')} | "
                    f"upload_time: {upload_time} | "
                    f"file_type: {f.get('file_type', '—')}"
                )
            appendix_parts.append("**Metadata:**\n" + "\n".join(meta_lines))

    if appendix_parts:
        llm_response = llm_response + "\n\n---\n" + "\n\n".join(appendix_parts)

    # -------------------------
    # Auto-title (LLM-generated, ChatGPT-style) on first message
    # -------------------------
    if is_first_message and session.title == "New Session":
        fallback_title = (query[:60] + "…") if len(query) > 60 else query
        title_prompt = (
            "Generate a short, specific chat title (max 6 words). "
            "No quotes, no trailing punctuation, no prefix like 'Title:'. "
            "Reply with only the title.\n\n"
            f"User: {query}\n"
            f"Assistant: {llm_response[:500]}\n\n"
            "Title:"
        )
        try:
            title_resp = requests.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": title_prompt,
                    "stream": False,
                    "options": {"num_predict": 20, "temperature": 0.3},
                },
                timeout=15,
            )
            generated = ""
            if title_resp.status_code == 200:
                raw = (title_resp.json().get("response") or "").strip()
                raw = raw.splitlines()[0] if raw else ""
                generated = raw.strip().strip('"').strip("'").rstrip(".!?,;:").strip()[:60]
            session.title = generated or fallback_title
        except requests.RequestException:
            session.title = fallback_title
        session.save(update_fields=["title"])

    # -------------------------
    # Save Assistant Message
    # -------------------------
    Message.objects.create(
        session=session,
        sender="assistant",
        text=llm_response
    )

    print(f"[{datetime.datetime.now()}] ASSISTANT MESSAGE SAVED: session={session.session_id}")

    print(f"[{datetime.datetime.now()}] PIPELINE COMPLETE: Returning response")
    return JsonResponse({
        "response": llm_response,
        "session_id": str(session.session_id),
        "session_title": session.title,
        "session_created": is_first_message,
    })