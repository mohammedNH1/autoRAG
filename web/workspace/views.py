"""
HTTP layer for the workspace app.

Each view does only:
  - request parsing
  - permission checks (delegated to services where possible)
  - calls a single service function
  - translates the service's (status, message) result into a response

Business logic lives in `workspace/services/*`.
"""

import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from pipeline.services.pipeline_registry import warm_pipeline_async
from workspace.models import Workspace, WorkspaceInvitation
from workspace.services import (
    dashboard_service,
    manage_members,
    session_service,
    workspace_settings,
)


# ---------------------------------------------------------------------------
# Request-scoped helpers — coupled to HTTP, so they stay in views.
# ---------------------------------------------------------------------------
def _get_user_workspace(request, workspace_id):
    """Return workspace if the request user owns it or is a member. 404 otherwise."""
    workspace = get_object_or_404(Workspace, workspace_id=workspace_id)
    if not manage_members.is_user_in_workspace(workspace, request.user):
        raise Http404("Workspace not found")
    return workspace


# ===========================================================================
# Workspace list + create (legacy deprecation stub)
# ===========================================================================
@login_required
def workspace_list(request):
    workspaces = (
        Workspace.objects
        .filter(Q(workspace_owner=request.user) | Q(users=request.user))
        .distinct()
        .order_by("-workspace_id")
    )
    pending_invites_count = WorkspaceInvitation.objects.filter(
        invited_user=request.user,
        status=WorkspaceInvitation.STATUS_PENDING,
    ).count()
    return render(request, "workspace/workspace_list.html", {
        "workspaces":            workspaces,
        "pending_invites_count": pending_invites_count,
    })


@csrf_exempt
@login_required
@require_POST
def create_workspace(request):
    # DEPRECATED: workspaces are now created atomically alongside their
    # RAG configuration via /submit-answers/.
    return JsonResponse(
        {"error": "Workspace creation requires the full RAG questionnaire. Use /submit-answers/."},
        status=410,
    )


# ===========================================================================
# Invitations
# ===========================================================================
@login_required
@require_GET
def list_invitations(request):
    invites = (
        WorkspaceInvitation.objects
        .filter(invited_user=request.user, status=WorkspaceInvitation.STATUS_PENDING)
        .select_related("workspace", "invited_by")
    )
    return JsonResponse({
        "invitations": [
            {
                "invitation_id":  inv.invitation_id,
                "workspace_id":   inv.workspace.workspace_id,
                "workspace_name": inv.workspace.workspace_name or f"Workspace {inv.workspace.workspace_id}",
                "role":           inv.role,
                "role_label":     manage_members.role_label(inv.role),
                "invited_by":     manage_members.user_display_name(inv.invited_by) if inv.invited_by else "Someone",
                "created_at":     inv.created_at.isoformat(),
            }
            for inv in invites
        ],
    })


@csrf_exempt
@login_required
@require_POST
def accept_invitation(request, invitation_id):
    invite = get_object_or_404(WorkspaceInvitation, pk=invitation_id, invited_user=request.user)
    if invite.status != WorkspaceInvitation.STATUS_PENDING:
        return JsonResponse({"error": "Invitation already responded to."}, status=400)

    manage_members.accept_pending_invitation(invite, request.user, timezone.now())
    return JsonResponse({
        "status":       "accepted",
        "workspace_id": invite.workspace.workspace_id,
    })


@csrf_exempt
@login_required
@require_POST
def reject_invitation(request, invitation_id):
    invite = get_object_or_404(WorkspaceInvitation, pk=invitation_id, invited_user=request.user)
    if invite.status != WorkspaceInvitation.STATUS_PENDING:
        return JsonResponse({"error": "Invitation already responded to."}, status=400)

    manage_members.reject_pending_invitation(invite, timezone.now())
    return JsonResponse({"status": "rejected"})


# ===========================================================================
# Members page + mutations
# ===========================================================================
@login_required
def members(request, workspace_id):
    workspace = _get_user_workspace(request, workspace_id)
    member_rows = manage_members.list_member_rows(workspace, request.user)

    return render(request, "workspace/members.html", {
        "workspace":           workspace,
        "workspace_id":        workspace_id,
        "members":             member_rows,
        "member_count":        len(member_rows),
        "owner_count":         sum(1 for row in member_rows if row["is_owner"]),
        "contributors_count":  sum(1 for row in member_rows if row["activity_total"] > 0),
        "questions_count":     sum(row["questions_count"] for row in member_rows),
        "can_manage_members":  manage_members.can_manage_members(workspace, request.user),
        "is_owner":            workspace.workspace_owner_id == request.user.id,
        "role_choices": [
            {"value": role, "label": manage_members.role_label(role)}
            for role in manage_members.MANAGEABLE_ROLES
        ],
    })


@login_required
@require_POST
def add_member(request, workspace_id):
    workspace = _get_user_workspace(request, workspace_id)
    email = (request.POST.get("email") or "").strip()
    role  = (request.POST.get("role") or "member").strip().lower()

    status, message = manage_members.invite_member_by_email(workspace, request.user, email, role)
    _flash(request, status, message)
    return redirect("workspace_members", workspace_id=workspace_id)


@login_required
@require_POST
def change_member_role(request, workspace_id, user_id):
    workspace = _get_user_workspace(request, workspace_id)
    new_role  = (request.POST.get("role") or "").strip().lower()

    User = get_user_model()
    target_user = get_object_or_404(User, pk=user_id)

    status, message = manage_members.change_role(workspace, request.user, target_user, new_role)
    _flash(request, status, message)
    return redirect("workspace_members", workspace_id=workspace_id)


@login_required
@require_POST
def remove_member(request, workspace_id, user_id):
    workspace = _get_user_workspace(request, workspace_id)
    User = get_user_model()
    target_user = get_object_or_404(User, pk=user_id)

    status, message = manage_members.remove_member_from_workspace(workspace, request.user, target_user)
    _flash(request, status, message)
    return redirect("workspace_members", workspace_id=workspace_id)


# ===========================================================================
# Chat page (rendered HTML)
# ===========================================================================
@login_required
def chat_page(request, workspace_id, session_id=None):
    workspace = _get_user_workspace(request, workspace_id)

    # Kick off pipeline loading in the background so the page renders
    # immediately. By the time the user sends their first query the
    # embedding + reranker are usually already in RAM.
    if hasattr(workspace, "config"):
        warm_pipeline_async(workspace_id, workspace.config)

    sessions = session_service.list_user_sessions(workspace, request.user)

    active_session = None
    if session_id is not None:
        active_session = session_service.get_user_session(workspace, request.user, session_id)
        if active_session is None:
            # URL points at a session this user doesn't own or that doesn't exist.
            return redirect("chat_page", workspace_id=workspace_id)

    initial_messages = session_service.serialize_messages(active_session) if active_session else []

    return render(request, "chat.html", {
        "workspace":              workspace,
        "workspace_id":           workspace_id,
        "workspace_name":         workspace.workspace_name,
        "sessions":               sessions,
        "active_session":         active_session,
        "active_session_id":      str(active_session.session_id) if active_session else "",
        "session_name":           active_session.title if active_session else "New Session",
        "initial_messages":       initial_messages,
        "create_session_url":     reverse("create_session", args=[workspace_id]),
        "workspace_chat_root_url": reverse("chat_page", args=[workspace_id]),
        "api_base_url":           "",
    })


# ===========================================================================
# Sessions (JSON endpoints)
# ===========================================================================
@login_required
@require_GET
def list_sessions(request, workspace_id):
    workspace = _get_user_workspace(request, workspace_id)
    sessions  = session_service.list_user_sessions(workspace, request.user)
    return JsonResponse({
        "sessions": [
            session_service.serialize_session_summary(s, reverse("chat_session", args=[workspace_id, s.session_id]))
            for s in sessions
        ],
    })


@csrf_exempt
@login_required
@require_POST
def create_session(request, workspace_id):
    workspace = _get_user_workspace(request, workspace_id)
    session = session_service.create_blank_session(workspace, request.user)
    return JsonResponse({
        "session_id": str(session.session_id),
        "title":      session.title,
        "url":        reverse("chat_session", args=[workspace_id, session.session_id]),
    })


@login_required
@require_GET
def session_messages(request, workspace_id, session_id):
    workspace = _get_user_workspace(request, workspace_id)
    session   = session_service.get_user_session(workspace, request.user, session_id)
    if session is None:
        return JsonResponse({"error": "Session not found"}, status=404)
    return JsonResponse({
        "session_id": str(session.session_id),
        "title":      session.title,
        "messages":   session_service.serialize_messages(session),
    })


@csrf_exempt
@login_required
@require_POST
def rename_session(request, workspace_id, session_id):
    workspace = _get_user_workspace(request, workspace_id)
    session   = session_service.get_user_session(workspace, request.user, session_id)
    if session is None:
        return JsonResponse({"error": "Session not found"}, status=404)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    status, payload = session_service.rename(session, data.get("title"))
    if status != "ok":
        return JsonResponse({"error": payload}, status=400)
    return JsonResponse({"session_id": str(session.session_id), "title": payload})


@csrf_exempt
@login_required
@require_POST
def delete_session(request, workspace_id, session_id):
    workspace = _get_user_workspace(request, workspace_id)
    session   = session_service.get_user_session(workspace, request.user, session_id)
    if session is None:
        return JsonResponse({"error": "Session not found"}, status=404)
    session_service.delete(session)
    return JsonResponse({"status": "deleted"})


# ===========================================================================
# Workspace settings
# ===========================================================================
@login_required
def workspace_settings_page(request, workspace_id):
    workspace = _get_user_workspace(request, workspace_id)
    if not workspace_settings.can_edit_settings(workspace, request.user):
        messages.error(request, "Only the workspace owner or an admin can view settings.")
        return redirect("chat_page", workspace_id=workspace_id)

    config = getattr(workspace, "config", None)
    return render(request, "workspace/settings.html", {
        "workspace":      workspace,
        "workspace_id":   workspace_id,
        "workspace_name": workspace.workspace_name,
        "is_owner":       workspace.workspace_owner_id == request.user.id,
        "can_edit":       True,
        "config":         config,
        "raw_answers":    (config.raw_answers or {}) if config else {},
    })


@login_required
@require_POST
def update_workspace_general(request, workspace_id):
    workspace = _get_user_workspace(request, workspace_id)
    if not workspace_settings.can_edit_settings(workspace, request.user):
        messages.error(request, "You don't have permission to edit workspace settings.")
        return redirect("workspace_settings", workspace_id=workspace_id)

    status, message = workspace_settings.update_general_details(
        workspace,
        request.POST.get("name"),
        request.POST.get("description"),
    )
    _flash(request, status, message)
    return redirect("workspace_settings", workspace_id=workspace_id)


@login_required
@require_POST
def update_workspace_config(request, workspace_id):
    workspace = _get_user_workspace(request, workspace_id)
    if not workspace_settings.can_edit_settings(workspace, request.user):
        messages.error(request, "You don't have permission to edit RAG configuration.")
        return redirect("workspace_settings", workspace_id=workspace_id)

    status, message = workspace_settings.update_rag_config(
        workspace, request.user, request.POST,
    )
    _flash(request, status, message)
    return redirect("workspace_settings", workspace_id=workspace_id)


@login_required
@require_POST
def delete_workspace(request, workspace_id):
    workspace = _get_user_workspace(request, workspace_id)
    status, message = workspace_settings.delete_workspace_with_confirmation(
        workspace, request.user, request.POST.get("confirm_name"),
    )
    _flash(request, status, message)
    if status == "ok":
        return redirect("workspace_list")
    return redirect("workspace_settings", workspace_id=workspace_id)


@login_required
@require_POST
def leave_workspace(request, workspace_id):
    workspace = _get_user_workspace(request, workspace_id)
    status, message = workspace_settings.leave_workspace_for_user(workspace, request.user)
    _flash(request, status, message)
    if status == "forbidden":
        return redirect("workspace_settings", workspace_id=workspace_id)
    return redirect("workspace_list")


@login_required
@require_POST
def generate_workspace_api_key(request, workspace_id):
    """Owner-only API key (re)generation. Raw key is returned once and never stored."""
    workspace = _get_user_workspace(request, workspace_id)
    try:
        raw_key, created_at_iso = workspace_settings.rotate_api_key(workspace, request.user)
    except PermissionError as exc:
        return JsonResponse({"error": str(exc)}, status=403)

    return JsonResponse({
        "api_key":    raw_key,  # shown ONCE
        "created_at": created_at_iso,
    })


# ===========================================================================
# Dashboard
# ===========================================================================
@login_required
def dashboard(request, workspace_id):
    workspace = _get_user_workspace(request, workspace_id)
    can_view_audit_trail = workspace_settings.can_edit_settings(workspace, request.user)
    context = dashboard_service.build_dashboard_context(workspace, request.user, can_view_audit_trail)
    return render(request, "workspace/dashboard.html", context)


# ---------------------------------------------------------------------------
# Flash helper — maps service status codes to the right messages.* call.
# ---------------------------------------------------------------------------
_INFO_STATUSES = {"already_member", "duplicate", "not_a_member", "no_change"}


def _flash(request, status, message):
    """Translate a service result tuple into a Django flash message."""
    if not message:
        return
    if status == "ok":
        messages.success(request, message)
    elif status in _INFO_STATUSES:
        messages.info(request, message)
    else:
        messages.error(request, message)
