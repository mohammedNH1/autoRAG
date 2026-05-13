"""
HTTP views for the RAG pipeline:
  - questionnaire_page / questionnaire   → workspace + RAG config creation
  - query_handling                       → web chat query endpoint
"""

import datetime
import json

import requests
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from pipeline.services.query_service import (
    OLLAMA_TITLE_MODEL,
    OLLAMA_URL,
    run_query,
)
from pipeline.services.questionnaire_mapper import (
    REQUIRED_QUESTIONNAIRE_FIELDS,
    add_metadata,
    determine_chunking_strategy,
    embedding_reranker,
    reference,
    temperature,
    top_k,
    top_p,
)
from workspace.models import (
    Message,
    Session,
    Workspace,
    WorkspaceConfig,
    WorkspaceMembership,
)


# ----------------------------------------------------------------------------
# Questionnaire
# ----------------------------------------------------------------------------


def questionnaire_page(request):
    return render(request, "questionnaire.html")


@csrf_exempt
@login_required
def questionnaire(request):
    """Create (or attach a config to) a workspace from questionnaire answers."""
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    content_type = (request.META.get("CONTENT_TYPE") or "").lower()
    image_file = None
    if content_type.startswith("multipart/form-data"):
        data = {k: v for k, v in request.POST.items()}
        image_file = request.FILES.get("workspace_image")
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

    # New workspaces require a name + image; the legacy "attach config to an
    # existing workspace" flow doesn't need either.
    if not workspace_id:
        validation_error = _validate_new_workspace_inputs(name, image_file)
        if validation_error:
            return JsonResponse({"error": validation_error}, status=400)

    embedding_config = embedding_reranker(data.get("language"), data.get("use_case"))
    config_values = {
        "k_value":           top_k(data.get("reference")),
        "reference_flag":    reference(data.get("reference")),
        "temp_value":        temperature(data.get("temperature")),
        "top_p_final":       top_p(data.get("top_p")),
        "metadata_flag":     add_metadata(data.get("metadata")),
        "chunking_strategy": determine_chunking_strategy(data.get("chunking_strategy")),
    }

    # Atomic: workspace + owner membership + config all succeed, or none persist.
    try:
        with transaction.atomic():
            if workspace_id:
                workspace = Workspace.objects.get(workspace_id=workspace_id)
                if not _user_is_member(workspace, request.user):
                    return JsonResponse({"error": "Forbidden"}, status=403)
            else:
                workspace = Workspace.objects.create(
                    workspace_name=name,
                    workspace_description=description,
                    workspace_owner=request.user,
                    workspace_image=image_file,
                )
                WorkspaceMembership.objects.create(
                    workspace=workspace, user=request.user, role="owner",
                )

            WorkspaceConfig.objects.create(
                workspace=workspace,
                retrieval_type="none",
                re_ranker=embedding_config["reranker_model"],
                embedding_model=embedding_config["embedding_model"],
                chunking_strategy=config_values["chunking_strategy"],
                distance_metric="cosine",
                temperature=config_values["temp_value"],
                top_p=config_values["top_p_final"],
                top_k=config_values["k_value"],
                is_citation=config_values["reference_flag"],
                metadata_flag=config_values["metadata_flag"],
                raw_answers={f: data.get(f) for f in REQUIRED_QUESTIONNAIRE_FIELDS},
            )
    except Workspace.DoesNotExist:
        return JsonResponse({"error": "Workspace not found"}, status=404)

    return JsonResponse({
        "status":       "success",
        "workspace_id": workspace.workspace_id,
        "config": {
            "embedding":         embedding_config,
            "top_k":             config_values["k_value"],
            "reference":         config_values["reference_flag"],
            "temperature":       config_values["temp_value"],
            "top_p":             config_values["top_p_final"],
            "metadata":          config_values["metadata_flag"],
            "chunking_strategy": config_values["chunking_strategy"],
        },
    })


def _validate_new_workspace_inputs(name, image_file):
    if not name:
        return "Workspace name is required"
    if len(name) > 150:
        return "Name must be 150 characters or fewer"
    # Image is optional — but if one was uploaded, it must be a valid image
    # and within the 5 MB cap.
    if image_file is not None:
        if not (image_file.content_type or "").startswith("image/"):
            return "Uploaded file must be an image"
        if image_file.size > 5 * 1024 * 1024:
            return "Image must be 5 MB or smaller"
    return None


def _user_is_member(workspace, user):
    return (
        workspace.workspace_owner_id == user.id
        or WorkspaceMembership.objects.filter(workspace=workspace, user=user).exists()
    )


# ----------------------------------------------------------------------------
# Web chat query endpoint
# ----------------------------------------------------------------------------


@csrf_exempt
@login_required
def query_handling(request):
    """Web chat endpoint — runs the RAG pipeline and persists session/messages."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    workspace_id = int(data.get("workspace_id") or 0)
    session_id   = data.get("session_id")
    query        = (data.get("message") or "").strip()
    if not workspace_id or not query:
        return JsonResponse(
            {"error": "workspace_id and message are required"}, status=400
        )

    try:
        workspace = Workspace.objects.get(workspace_id=workspace_id)
    except Workspace.DoesNotExist:
        return JsonResponse({"error": "Workspace not found"}, status=404)

    if not _user_is_member(workspace, request.user):
        return JsonResponse({"error": "Forbidden"}, status=403)
    if not hasattr(workspace, "config"):
        return JsonResponse(
            {"error": "Workspace is not configured yet"}, status=400
        )

    session, is_first_message = _get_or_create_session(
        workspace, request.user, session_id,
    )
    Message.objects.create(session=session, sender="user", text=query)

    result = run_query(workspace, query)

    if result.no_documents:
        Message.objects.create(session=session, sender="assistant", text=result.answer)
        return _chat_response(result.answer, session, is_first_message)

    llm_response = result.answer + _format_appendix(
        result.sources, result.is_citation, result.metadata_flag,
    )

    if is_first_message and session.title == "New Session":
        session.title = _generate_session_title(query, llm_response)
        session.save(update_fields=["title"])

    Message.objects.create(session=session, sender="assistant", text=llm_response)
    return _chat_response(llm_response, session, is_first_message)


def _chat_response(text, session, is_first_message):
    return JsonResponse({
        "response":        text,
        "session_id":      str(session.session_id),
        "session_title":   session.title,
        "session_created": is_first_message,
    })


def _get_or_create_session(workspace, user, session_id):
    """Resolve the request's session; create a fresh one if the id is missing/invalid."""
    session = None
    if session_id:
        try:
            session = Session.objects.filter(
                session_id=session_id, workspace=workspace, user=user,
            ).first()
        except (ValueError, ValidationError):
            session = None

    if not session:
        session = Session.objects.create(
            workspace=workspace, user=user, title="New Session",
        )

    is_first_message = not session.messages.exists()
    return session, is_first_message


# Document-level payload fields used when grouping chunks back into source documents.
_DOC_LEVEL_FIELDS = {
    "document_id", "document_title", "uploaded_by", "upload_time", "file_type", "source",
}


def _format_appendix(sources, is_citation, metadata_flag):
    """Render a per-document Sources/Metadata appendix for the chat reply."""
    if not sources or (not is_citation and not metadata_flag):
        return ""

    docs = {}
    for s in sources:
        doc_id = s.get("document_id", s.get("document_title", "unknown"))
        if doc_id not in docs:
            docs[doc_id] = {
                "fields": {k: v for k, v in s.items() if k in _DOC_LEVEL_FIELDS},
                "pages":  [],
            }
        page = s.get("section") or s.get("page", "?")
        if page not in docs[doc_id]["pages"]:
            docs[doc_id]["pages"].append(page)

    parts = []
    if is_citation:
        lines = [
            f'- "{d["fields"].get("document_title", "Unknown")}" — '
            f'Pages: {", ".join(str(p) for p in d["pages"])}'
            for d in docs.values()
        ]
        parts.append("**Sources:**\n" + "\n".join(lines))

    if metadata_flag:
        lines = []
        for i, d in enumerate(docs.values(), 1):
            f = d["fields"]
            raw_time = f.get("upload_time", "")
            try:
                upload_time = datetime.datetime.fromisoformat(raw_time).strftime("%d %b %Y, %H:%M")
            except (ValueError, TypeError):
                upload_time = raw_time
            lines.append(
                f"[{i}] uploaded_by: {f.get('uploaded_by', '—')} | "
                f"upload_time: {upload_time} | "
                f"file_type: {f.get('file_type', '—')}"
            )
        parts.append("**Metadata:**\n" + "\n".join(lines))

    return "\n\n---\n" + "\n\n".join(parts) if parts else ""


def _generate_session_title(query, llm_response):
    """Ask the LLM for a short title; fall back to a truncated query on failure."""
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
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model":   OLLAMA_TITLE_MODEL,
                "prompt":  title_prompt,
                "stream":  False,
                "options": {"num_predict": 20, "temperature": 0.3},
            },
            timeout=15,
        )
    except requests.RequestException:
        return fallback_title

    if resp.status_code != 200:
        return fallback_title

    raw = (resp.json().get("response") or "").strip()
    first_line = raw.splitlines()[0] if raw else ""
    cleaned = first_line.strip().strip('"').strip("'").rstrip(".!?,;:").strip()[:60]
    return cleaned or fallback_title
