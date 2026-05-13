import json
from collections import Counter

from django.shortcuts import get_object_or_404, render, redirect
from django.http import JsonResponse, Http404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Count
from django.urls import reverse
from django.utils import timezone

from workspace.models import Workspace, WorkspaceMembership, WorkspaceInvitation, Session, Message
from pipeline.services.pipeline_registry import get_pipeline
from pipeline.api.keys import generate_api_key, hash_api_key


# Roles that the workspace owner can assign to other members.
MANAGEABLE_ROLES = ("member", "admin", "content_manager")
INVITER_ROLES   = ("owner", "admin", "content_manager")
ROLE_LABELS = {
    "owner":           "Owner",
    "admin":           "Admin",
    "content_manager": "Content Manager",
    "member":          "User",
    "editor":          "Editor",
    "viewer":          "Viewer",
}


def _role_label(role):
    return ROLE_LABELS.get(role, (role or "").replace("_", " ").title() or "User")





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


def _user_display_name(user):
    if user is None:
        return "Unknown user"
    return user.get_full_name() or user.email or user.username or "Unknown user"


def _user_initials(user):
    display_name = _user_display_name(user)
    parts = [part for part in display_name.replace("@", " ").replace(".", " ").split() if part]
    if not parts:
        return "U"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return f"{parts[0][0]}{parts[-1][0]}".upper()


def _can_manage_members(workspace, user):
    return (
        workspace.workspace_owner_id == user.id
        or WorkspaceMembership.objects.filter(
            workspace=workspace,
            user=user,
            role__in=list(INVITER_ROLES),
        ).exists()
    )


def _build_member_row(workspace, user, role, current_user):
    sessions_count = Session.objects.filter(workspace=workspace, user=user).count()
    questions_count = Message.objects.filter(
        session__workspace=workspace,
        session__user=user,
        sender="user",
    ).count()
    documents_count = workspace.documents.filter(uploaded_by=user).count()

    return {
        "user": user,
        "display_name": _user_display_name(user),
        "initials": _user_initials(user),
        "email": user.email or user.username,
        "role": role,
        "role_label": _role_label(role),
        "is_owner": workspace.workspace_owner_id == user.id,
        "is_current_user": current_user.id == user.id,
        "sessions_count": sessions_count,
        "questions_count": questions_count,
        "documents_count": documents_count,
        "activity_total": sessions_count + questions_count + documents_count,
        "last_seen": user.last_login or user.date_joined,
        "status_label": "You" if current_user.id == user.id else ("Active" if user.last_login else "No login yet"),
    }

### Added by rayan to build the time saved chart
# Based on the McKinsey-style estimate that employees spend 1.8 hours per day
# searching for and gathering information.
TIME_SAVED_MINUTES_PER_ACTIVE_DAY = 108
WEEKDAY_LABELS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
CHART_W, CHART_H, CHART_TOP, CHART_BOTTOM = 365, 80, 12, 62


def _smooth_svg_path(points):
    path = f"M {points[0][0]:.2f} {points[0][1]:.2f}"
    for index, (p1, p2) in enumerate(zip(points, points[1:])):
        p0 = points[index - 1] if index else p1
        p3 = points[index + 2] if index + 2 < len(points) else p2
        c1x = p1[0] + (p2[0] - p0[0]) / 6
        c1y = p1[1] + (p2[1] - p0[1]) / 6
        c2x = p2[0] - (p3[0] - p1[0]) / 6
        c2y = p2[1] - (p3[1] - p1[1]) / 6
        path += f" C {c1x:.2f} {c1y:.2f}, {c2x:.2f} {c2y:.2f}, {p2[0]:.2f} {p2[1]:.2f}"
    return path


def _format_time_saved(minutes):
    minutes = int(minutes or 0)
    if minutes < 60:
        return f"{minutes} {'min' if minutes == 1 else 'mins'}"

    hours = minutes / 60
    hours_value = int(hours) if hours.is_integer() else round(hours, 1)
    return f"{hours_value} {'hour' if hours_value == 1 else 'hours'}"


@login_required
def workspace_list(request):
    workspaces = Workspace.objects.filter(
        Q(workspace_owner=request.user) | Q(users=request.user)
    ).distinct().order_by('-workspace_id')

    pending_invites_count = WorkspaceInvitation.objects.filter(
        invited_user=request.user,
        status=WorkspaceInvitation.STATUS_PENDING,
    ).count()

    return render(request, "workspace/workspace_list.html", {
        "workspaces": workspaces,
        "pending_invites_count": pending_invites_count,
    })


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
                "invitation_id":   inv.invitation_id,
                "workspace_id":    inv.workspace.workspace_id,
                "workspace_name":  inv.workspace.workspace_name or f"Workspace {inv.workspace.workspace_id}",
                "role":            inv.role,
                "role_label":      _role_label(inv.role),
                "invited_by":      _user_display_name(inv.invited_by) if inv.invited_by else "Someone",
                "created_at":      inv.created_at.isoformat(),
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

    workspace = invite.workspace
    already_member = (
        workspace.workspace_owner_id == request.user.id
        or WorkspaceMembership.objects.filter(workspace=workspace, user=request.user).exists()
    )
    if not already_member:
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=request.user,
            role=invite.role,
        )

    invite.status = WorkspaceInvitation.STATUS_ACCEPTED
    invite.responded_at = timezone.now()
    invite.save(update_fields=["status", "responded_at"])

    return JsonResponse({
        "status": "accepted",
        "workspace_id": workspace.workspace_id,
    })


@csrf_exempt
@login_required
@require_POST
def reject_invitation(request, invitation_id):
    invite = get_object_or_404(WorkspaceInvitation, pk=invitation_id, invited_user=request.user)
    if invite.status != WorkspaceInvitation.STATUS_PENDING:
        return JsonResponse({"error": "Invitation already responded to."}, status=400)

    invite.status = WorkspaceInvitation.STATUS_REJECTED
    invite.responded_at = timezone.now()
    invite.save(update_fields=["status", "responded_at"])

    return JsonResponse({"status": "rejected"})


@csrf_exempt
@login_required
@require_POST
def create_workspace(request):
    # DEPRECATED: workspaces are now created atomically alongside their
    # RAG configuration via /submit-answers/. This endpoint refuses
    # to create workspaces standalone so orphaned ones can never appear.
    return JsonResponse(
        {"error": "Workspace creation requires the full RAG questionnaire. Use /submit-answers/."},
        status=410,
    )


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
        "initial_messages": initial_messages,
        "create_session_url": reverse('create_session', args=[workspace_id]),
        "workspace_chat_root_url": reverse('chat_page', args=[workspace_id]),
        "api_base_url": "",
    })


@login_required
def members(request, workspace_id):
    workspace = _get_user_workspace(request, workspace_id)

    member_rows = []
    seen_user_ids = set()

    for membership in WorkspaceMembership.objects.filter(workspace=workspace).select_related("user"):
        user = membership.user
        role = "owner" if workspace.workspace_owner_id == user.id else (membership.role or "member")
        member_rows.append(_build_member_row(workspace, user, role, request.user))
        seen_user_ids.add(user.id)

    if workspace.workspace_owner and workspace.workspace_owner_id not in seen_user_ids:
        member_rows.append(_build_member_row(workspace, workspace.workspace_owner, "owner", request.user))

    member_rows.sort(key=lambda row: (0 if row["is_owner"] else 1, row["display_name"].lower()))
    can_manage_members = _can_manage_members(workspace, request.user)

    return render(request, "workspace/members.html", {
        "workspace": workspace,
        "workspace_id": workspace_id,
        "members": member_rows,
        "member_count": len(member_rows),
        "owner_count": sum(1 for row in member_rows if row["is_owner"]),
        "contributors_count": sum(1 for row in member_rows if row["activity_total"] > 0),
        "questions_count": sum(row["questions_count"] for row in member_rows),
        "can_manage_members": can_manage_members,
        "is_owner": workspace.workspace_owner_id == request.user.id,
        "role_choices": [
            {"value": role, "label": _role_label(role)} for role in MANAGEABLE_ROLES
        ],
    })


@login_required
@require_POST
def add_member(request, workspace_id):
    workspace = _get_user_workspace(request, workspace_id)
    if not _can_manage_members(workspace, request.user):
        messages.error(request, "You don't have permission to invite members.")
        return redirect("workspace_members", workspace_id=workspace_id)

    email = (request.POST.get("email") or "").strip()
    role = (request.POST.get("role") or "member").strip().lower()
    if role not in MANAGEABLE_ROLES:
        role = "member"

    if not email:
        messages.error(request, "Enter the member email address.")
        return redirect("workspace_members", workspace_id=workspace_id)

    User = get_user_model()
    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        messages.error(request, "No account was found for that email.")
        return redirect("workspace_members", workspace_id=workspace_id)

    if user.id == workspace.workspace_owner_id or WorkspaceMembership.objects.filter(workspace=workspace, user=user).exists():
        messages.info(request, "That user is already in this workspace.")
        return redirect("workspace_members", workspace_id=workspace_id)

    existing_pending = WorkspaceInvitation.objects.filter(
        workspace=workspace,
        invited_user=user,
        status=WorkspaceInvitation.STATUS_PENDING,
    ).first()
    if existing_pending:
        messages.info(request, f"{_user_display_name(user)} already has a pending invitation.")
        return redirect("workspace_members", workspace_id=workspace_id)

    WorkspaceInvitation.objects.create(
        workspace=workspace,
        invited_user=user,
        invited_by=request.user,
        role=role,
        status=WorkspaceInvitation.STATUS_PENDING,
    )
    messages.success(request, f"Invitation sent to {_user_display_name(user)}.")
    return redirect("workspace_members", workspace_id=workspace_id)


@login_required
@require_POST
def change_member_role(request, workspace_id, user_id):
    workspace = _get_user_workspace(request, workspace_id)

    # Only the workspace owner can change roles.
    if workspace.workspace_owner_id != request.user.id:
        messages.error(request, "Only the workspace owner can change member roles.")
        return redirect("workspace_members", workspace_id=workspace_id)

    if user_id == workspace.workspace_owner_id:
        messages.error(request, "The workspace owner's role cannot be changed.")
        return redirect("workspace_members", workspace_id=workspace_id)

    new_role = (request.POST.get("role") or "").strip().lower()
    if new_role not in MANAGEABLE_ROLES:
        messages.error(request, "Invalid role.")
        return redirect("workspace_members", workspace_id=workspace_id)

    User = get_user_model()
    target_user = get_object_or_404(User, pk=user_id)

    membership = WorkspaceMembership.objects.filter(workspace=workspace, user=target_user).first()
    if membership is None:
        messages.error(request, "That user is not a member of this workspace.")
        return redirect("workspace_members", workspace_id=workspace_id)

    if membership.role == new_role:
        return redirect("workspace_members", workspace_id=workspace_id)

    membership.role = new_role
    membership.save(update_fields=["role"])
    messages.success(
        request,
        f"{_user_display_name(target_user)} is now {_role_label(new_role)}.",
    )
    return redirect("workspace_members", workspace_id=workspace_id)


@login_required
@require_POST
def remove_member(request, workspace_id, user_id):
    workspace = _get_user_workspace(request, workspace_id)
    if not _can_manage_members(workspace, request.user):
        messages.error(request, "Only workspace owners can remove members.")
        return redirect("workspace_members", workspace_id=workspace_id)

    User = get_user_model()
    user = get_object_or_404(User, pk=user_id)

    if user.id == workspace.workspace_owner_id:
        messages.error(request, "The workspace owner cannot be removed.")
        return redirect("workspace_members", workspace_id=workspace_id)

    deleted, _ = WorkspaceMembership.objects.filter(workspace=workspace, user=user).delete()
    if deleted:
        messages.success(request, f"{_user_display_name(user)} was removed from this workspace.")
    else:
        messages.info(request, "That user is not a member of this workspace.")

    return redirect("workspace_members", workspace_id=workspace_id)


@login_required
def workspace_settings(request, workspace_id):
    workspace = _get_user_workspace(request, workspace_id)

    # Only owners and admins can access the settings page at all.
    if not _can_edit_settings(workspace, request.user):
        messages.error(request, "Only the workspace owner or an admin can view settings.")
        return redirect("chat_page", workspace_id=workspace_id)

    is_owner = workspace.workspace_owner_id == request.user.id
    can_edit = True  # already gated above

    config = getattr(workspace, 'config', None)
    raw = (config.raw_answers or {}) if config else {}

    return render(request, "workspace/settings.html", {
        "workspace": workspace,
        "workspace_id": workspace_id,
        "workspace_name": workspace.workspace_name,
        "is_owner": is_owner,
        "can_edit": can_edit,
        "config": config,
        "raw_answers": raw,
    })


def _can_edit_settings(workspace, user):
    return (
        workspace.workspace_owner_id == user.id
        or WorkspaceMembership.objects.filter(
            workspace=workspace, user=user, role__in=["owner", "admin"],
        ).exists()
    )


@login_required
@require_POST
def update_workspace_general(request, workspace_id):
    workspace = _get_user_workspace(request, workspace_id)
    if not _can_edit_settings(workspace, request.user):
        messages.error(request, "You don't have permission to edit workspace settings.")
        return redirect("workspace_settings", workspace_id=workspace_id)

    name = (request.POST.get("name") or "").strip()
    description = (request.POST.get("description") or "").strip()

    if not name:
        messages.error(request, "Workspace name is required.")
        return redirect("workspace_settings", workspace_id=workspace_id)
    if len(name) > 150:
        messages.error(request, "Name must be 150 characters or fewer.")
        return redirect("workspace_settings", workspace_id=workspace_id)

    workspace.workspace_name = name
    workspace.workspace_description = description
    workspace.save(update_fields=["workspace_name", "workspace_description"])
    messages.success(request, "Workspace details updated.")
    return redirect("workspace_settings", workspace_id=workspace_id)


@login_required
@require_POST
def update_workspace_config(request, workspace_id):
    workspace = _get_user_workspace(request, workspace_id)
    if not _can_edit_settings(workspace, request.user):
        messages.error(request, "You don't have permission to edit RAG configuration.")
        return redirect("workspace_settings", workspace_id=workspace_id)

    config = getattr(workspace, 'config', None)
    if config is None:
        messages.error(request, "Workspace has no configuration to edit.")
        return redirect("workspace_settings", workspace_id=workspace_id)

    # Import the questionnaire helpers locally to avoid circular import.
    from pipeline.views import (
        REQUIRED_QUESTIONNAIRE_FIELDS,
        embedding_reranker, top_k as _top_k, reference as _reference,
        temperature as _temperature, top_p as _top_p,
        up_to_date_docs, add_metadata, determine_chunking_strategy,
    )

    chunking_map = {
        'slide_deck':     'slide deck',
        'meeting_notes':  'meeting notes',
        'article':        'article',
        'research_paper': 'research paper',
        'policy':         'policy',
    }

    raw = {f: (request.POST.get(f) or "").strip() for f in REQUIRED_QUESTIONNAIRE_FIELDS}
    if not all(raw.values()):
        missing = [k for k, v in raw.items() if not v]
        messages.error(request, f"Missing answers: {', '.join(missing)}")
        return redirect("workspace_settings", workspace_id=workspace_id)

    # Normalize chunking_strategy from form value to backend-expected string.
    raw_chunk_form = raw["chunking_strategy"]
    raw["chunking_strategy"] = chunking_map.get(raw_chunk_form, raw_chunk_form)

    embedding_config  = embedding_reranker(raw["language"], raw["use_case"])
    config.embedding_model    = embedding_config["embedding_model"]
    config.re_ranker          = embedding_config["reranker_model"]
    config.top_k              = _top_k(raw["reference"])
    config.is_citation        = _reference(raw["reference"])
    config.temperature        = _temperature(raw["temperature"])
    config.top_p              = _top_p(raw["top_p"])
    config.metadata_flag      = add_metadata(raw["metadata"])
    config.chunking_strategy  = determine_chunking_strategy(raw["chunking_strategy"])
    # Persist form values back for next-time prefill.
    raw["chunking_strategy"] = raw_chunk_form
    config.raw_answers = raw
    config.save()

    messages.success(
        request,
        "RAG configuration updated. Note: changing embedding or chunking may require re-indexing existing documents.",
    )
    return redirect("workspace_settings", workspace_id=workspace_id)


@login_required
@require_POST
def delete_workspace(request, workspace_id):
    workspace = _get_user_workspace(request, workspace_id)
    if workspace.workspace_owner_id != request.user.id:
        messages.error(request, "Only the workspace owner can delete this workspace.")
        return redirect("workspace_settings", workspace_id=workspace_id)

    confirm = (request.POST.get("confirm_name") or "").strip()
    if confirm != (workspace.workspace_name or ""):
        messages.error(request, "Confirmation name does not match. Workspace not deleted.")
        return redirect("workspace_settings", workspace_id=workspace_id)

    workspace.delete()
    messages.success(request, "Workspace deleted.")
    return redirect("workspace_list")


@login_required
@require_POST
def generate_workspace_api_key(request, workspace_id):
    """
    Generate (or regenerate) the external API key for a workspace.

    Owner-only. The raw key is returned exactly once in this response.
    The DB only stores its SHA-256 hash, so regenerating invalidates
    every previously issued key for this workspace.
    """
    workspace = _get_user_workspace(request, workspace_id)
    if workspace.workspace_owner_id != request.user.id:
        return JsonResponse(
            {"error": "Only the workspace owner can manage the API key."},
            status=403,
        )

    raw_key = generate_api_key()
    workspace.api_key = hash_api_key(raw_key)
    workspace.api_key_created_at = timezone.now()
    workspace.save(update_fields=["api_key", "api_key_created_at"])

    return JsonResponse({
        "api_key":    raw_key,                                # shown ONCE
        "created_at": workspace.api_key_created_at.isoformat(),
    })


@login_required
@require_POST
def leave_workspace(request, workspace_id):
    workspace = _get_user_workspace(request, workspace_id)
    if workspace.workspace_owner_id == request.user.id:
        messages.error(request, "Owners cannot leave their own workspace. Delete it instead.")
        return redirect("workspace_settings", workspace_id=workspace_id)

    deleted, _ = WorkspaceMembership.objects.filter(
        workspace=workspace, user=request.user,
    ).delete()
    if deleted:
        messages.success(request, f"You left {workspace.workspace_name or 'this workspace'}.")
    return redirect("workspace_list")


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

### Added by rayan to build the dashboard page
@login_required
def dashboard(request, workspace_id):
    workspace = _get_user_workspace(request, workspace_id)

    user_messages = Message.objects.filter(session__workspace=workspace, sender='user')
    questions_count = user_messages.count()
    message_timestamps = list(user_messages.values_list('timestamp', flat=True))
    message_dates = [timezone.localtime(ts).date() for ts in message_timestamps]
    active_days_count = len(set(message_dates))
    week_ago = timezone.now() - timezone.timedelta(days=7)
    questions_this_week = user_messages.filter(timestamp__gte=week_ago).count()
    time_saved_minutes = active_days_count * TIME_SAVED_MINUTES_PER_ACTIVE_DAY
    documents_qs = workspace.documents.all()
    documents_count = documents_qs.count()

    productive_days = Counter(timezone.localtime(ts).strftime('%A') for ts in message_timestamps).most_common(3)
    today = timezone.localdate()
    week_start = today - timezone.timedelta(days=(today.weekday() + 1) % 7)
    week_end = week_start + timezone.timedelta(days=7)
    active_week_day_indexes = {
        (message_date - week_start).days
        for message_date in message_dates
        if week_start <= message_date < week_end
    }
    minutes = [
        TIME_SAVED_MINUTES_PER_ACTIVE_DAY if i in active_week_day_indexes else 0
        for i in range(7)
    ]
    time_saved_this_week_minutes = sum(minutes)
    max_minutes = max(minutes) or 1
    points = [(i * CHART_W / 6, CHART_BOTTOM - minutes[i] / max_minutes * (CHART_BOTTOM - CHART_TOP)) for i in range(7)]
    line_path = _smooth_svg_path(points)
    peak = max(range(7), key=lambda i: minutes[i]) if any(minutes) else min(max((today - week_start).days, 0), 6)
    peak_x, peak_y = points[peak]
    peak_date = week_start + timezone.timedelta(days=peak)
    day_suffix = "th" if 10 <= peak_date.day % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(peak_date.day % 10, "th")

    return render(request, "workspace/dashboard.html", {
        "workspace": workspace,
        "workspace_id": workspace_id,
        "is_empty": questions_count == 0 and documents_count == 0,
        "questions_count": questions_count,
        "questions_this_week": questions_this_week,
        "documents_count": documents_count,
        "docs_this_week": documents_qs.filter(upload_time__gte=week_ago).count(),
        "time_saved_display": _format_time_saved(time_saved_minutes),
        "time_saved_this_week_display": _format_time_saved(time_saved_this_week_minutes),
        "top_questions": list(user_messages.values('text').annotate(c=Count('text')).order_by('-c', 'text')[:5]),
        "top_documents": list(documents_qs.order_by('-upload_time')[:5].values('document_title', 'file')),
        "productive_days": productive_days,
        "time_chart": {
            "days": WEEKDAY_LABELS,
            "line": line_path,
            "fill": f"{line_path} L {CHART_W:.2f} {CHART_H:.2f} L 0.00 {CHART_H:.2f} Z",
            "dot_x": f"{peak_x:.2f}",
            "dot_y": f"{peak_y:.2f}",
            "tooltip_x": f"{max(38, min(CHART_W - 38, peak_x)):.2f}",
            "tooltip_y": f"{max(0, peak_y - 48):.2f}",
            "tooltip_value": _format_time_saved(minutes[peak]),
            "tooltip_date": f"{peak_date.strftime('%b')} {peak_date.day}{day_suffix}, {peak_date.year}",
        },
        "audit_trail": list(documents_qs.order_by('-upload_time')[:10].values('document_title', 'file', 'upload_time', 'uploaded_by__email')),
    })
