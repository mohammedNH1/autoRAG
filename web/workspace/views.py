import json

from django.shortcuts import get_object_or_404, render, redirect
from django.http import JsonResponse, Http404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.urls import reverse

from workspace.models import Workspace, WorkspaceMembership, Session
from pipeline.services.pipeline_registry import get_pipeline


def _get_user_workspace(request, workspace_id):
    """Return workspace if the request user owns it or is a member. 404 otherwise."""
    workspace = get_object_or_404(Workspace, workspace_id=workspace_id)
    is_member = (
        workspace.workspace_owner_id == request.user.id
        or WorkspaceMembership.objects.filter(
            workspace=workspace, user=request.user
        ).exists()
    )
    if not is_member:
        raise Http404("Workspace not found")
    return workspace


def _get_user_session(workspace, user, session_id):
    """Return the session if it belongs to this user in this workspace, else None."""
    return Session.objects.filter(
        workspace=workspace,
        user=user,
        session_id=session_id,
    ).first()


@login_required
def workspace_list(request):
    workspaces = Workspace.objects.filter(
        Q(workspace_owner=request.user) | Q(users=request.user)
    ).distinct().order_by('-workspace_id')

    return render(request, "workspace/workspace_list.html", {
        "workspaces": workspaces,
    })


@csrf_exempt
@login_required
@require_POST
def create_workspace(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    name = data.get("name", "").strip()
    description = data.get("description", "").strip()

    if not name:
        return JsonResponse({"error": "Workspace name is required"}, status=400)

    if len(name) > 150:
        return JsonResponse({"error": "Name must be 150 characters or fewer"}, status=400)

    workspace = Workspace.objects.create(
        workspace_name=name,
        workspace_description=description,
        workspace_owner=request.user,
    )

    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=request.user,
        role="owner",
    )

    return JsonResponse({
        "status": "success",
        "workspace_id": workspace.workspace_id,
    })


@login_required
def chat_page(request, workspace_id, session_id=None):
    workspace = _get_user_workspace(request, workspace_id)

    # Pre-warm pipeline only once the workspace has a config.
    if hasattr(workspace, 'config'):
        get_pipeline(workspace_id, workspace.config)

    sessions = Session.objects.filter(
        workspace=workspace,
        user=request.user,
    ).order_by('-created_at')

    active_session = None
    if session_id is not None:
        active_session = _get_user_session(workspace, request.user, session_id)
        if active_session is None:
            # URL points at a session this user doesn't own or that doesn't exist —
            # quietly fall back to the workspace root.
            return redirect('chat_page', workspace_id=workspace_id)

    initial_messages = []
    if active_session is not None:
        initial_messages = [
            {
                "message_id": str(m.message_id),
                "sender": m.sender,
                "text": m.text,
                "timestamp": m.timestamp.isoformat(),
            }
            for m in active_session.messages.all()
        ]

    return render(request, "chat.html", {
        "workspace": workspace,
        "workspace_id": workspace_id,
        "workspace_name": workspace.workspace_name,
        "sessions": sessions,
        "active_session": active_session,
        "active_session_id": str(active_session.session_id) if active_session else "",
        "session_name": active_session.title if active_session else "New Session",
        "initial_messages_json": json.dumps(initial_messages),
        "create_session_url": reverse('create_session', args=[workspace_id]),
        "workspace_chat_root_url": reverse('chat_page', args=[workspace_id]),
        "api_base_url": "",
    })


@login_required
@require_GET
def list_sessions(request, workspace_id):
    workspace = _get_user_workspace(request, workspace_id)
    sessions = Session.objects.filter(
        workspace=workspace, user=request.user,
    ).order_by('-created_at')
    return JsonResponse({
        "sessions": [
            {
                "session_id": str(s.session_id),
                "title": s.title,
                "created_at": s.created_at.isoformat(),
                "url": reverse('chat_session', args=[workspace_id, s.session_id]),
            }
            for s in sessions
        ],
    })


@csrf_exempt
@login_required
@require_POST
def create_session(request, workspace_id):
    workspace = _get_user_workspace(request, workspace_id)
    session = Session.objects.create(
        workspace=workspace,
        user=request.user,
        title="New Session",
    )
    return JsonResponse({
        "session_id": str(session.session_id),
        "title": session.title,
        "url": reverse('chat_session', args=[workspace_id, session.session_id]),
    })


@login_required
@require_GET
def session_messages(request, workspace_id, session_id):
    workspace = _get_user_workspace(request, workspace_id)
    session = _get_user_session(workspace, request.user, session_id)
    if session is None:
        return JsonResponse({"error": "Session not found"}, status=404)
    return JsonResponse({
        "session_id": str(session.session_id),
        "title": session.title,
        "messages": [
            {
                "message_id": str(m.message_id),
                "sender": m.sender,
                "text": m.text,
                "timestamp": m.timestamp.isoformat(),
            }
            for m in session.messages.all()
        ],
    })


@csrf_exempt
@login_required
@require_POST
def rename_session(request, workspace_id, session_id):
    workspace = _get_user_workspace(request, workspace_id)
    session = _get_user_session(workspace, request.user, session_id)
    if session is None:
        return JsonResponse({"error": "Session not found"}, status=404)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    title = (data.get("title") or "").strip()
    if not title:
        return JsonResponse({"error": "Title is required"}, status=400)
    if len(title) > 150:
        return JsonResponse({"error": "Title too long"}, status=400)
    session.title = title
    session.save(update_fields=["title"])
    return JsonResponse({"session_id": str(session.session_id), "title": session.title})


@csrf_exempt
@login_required
@require_POST
def delete_session(request, workspace_id, session_id):
    workspace = _get_user_workspace(request, workspace_id)
    session = _get_user_session(workspace, request.user, session_id)
    if session is None:
        return JsonResponse({"error": "Session not found"}, status=404)
    session.delete()
    return JsonResponse({"status": "deleted"})
