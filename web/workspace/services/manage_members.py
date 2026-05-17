"""
Member management — invitations, role changes, removals, display formatting.

Pure business logic — these functions accept domain objects (Workspace, User)
and never touch `request`/`HttpResponse`/`messages.error`. The view layer
handles HTTP concerns and translates the return values into flashes.
"""

from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from workspace.models import (
    Session,
    Message,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from workspace.services import activity_log


# ---------------------------------------------------------------------------
# Role constants — kept here so members.html can render them and so other
# services can validate without re-declaring.
# ---------------------------------------------------------------------------
MANAGEABLE_ROLES = ("member", "admin", "content_manager")
INVITER_ROLES    = ("owner", "admin", "content_manager")
ADMIN_ROLES      = ("owner", "admin")

ROLE_LABELS = {
    "owner":           _("Owner"),
    "admin":           _("Admin"),
    "content_manager": _("Content Manager"),
    "member":          _("User"),
    "editor":          _("Editor"),
    "viewer":          _("Viewer"),
}


# ---------------------------------------------------------------------------
# Display helpers — used by views, templates (via context), activity_log
# call sites, and the audit trail builder. Pure functions.
# ---------------------------------------------------------------------------
def role_label(role):
    return ROLE_LABELS.get(role, (role or "").replace("_", " ").title() or _("User"))


def user_display_name(user):
    if user is None:
        return "Unknown user"
    return user.get_full_name() or user.email or user.username or "Unknown user"


def user_initials(user):
    display_name = user_display_name(user)
    parts = [part for part in display_name.replace("@", " ").replace(".", " ").split() if part]
    if not parts:
        return "U"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return f"{parts[0][0]}{parts[-1][0]}".upper()


# ---------------------------------------------------------------------------
# Permission checks.
# ---------------------------------------------------------------------------
def can_manage_members(workspace, user):
    return (
        workspace.workspace_owner_id == user.id
        or WorkspaceMembership.objects.filter(
            workspace=workspace, user=user, role__in=list(INVITER_ROLES),
        ).exists()
    )


def is_user_in_workspace(workspace, user):
    """True if `user` owns the workspace or is a member of it."""
    return (
        workspace.workspace_owner_id == user.id
        or WorkspaceMembership.objects.filter(workspace=workspace, user=user).exists()
    )


def is_basic_member(workspace, user):
    """True if `user` is a workspace member with the plain 'member' role.

    Basic members only access chat sessions — Members/Documents/Dashboards/Settings
    pages are hidden and direct URL access is blocked.
    """
    if workspace is None or user is None or not user.is_authenticated:
        return False
    if workspace.workspace_owner_id == user.id:
        return False
    return WorkspaceMembership.objects.filter(
        workspace=workspace, user=user, role="member",
    ).exists()


# ---------------------------------------------------------------------------
# Member listing — builds the rows the members.html table renders.
# ---------------------------------------------------------------------------
def build_member_row(workspace, user, role, current_user):
    sessions_count  = Session.objects.filter(workspace=workspace, user=user).count()
    questions_count = Message.objects.filter(
        session__workspace=workspace,
        session__user=user,
        sender="user",
    ).count()
    documents_count = workspace.documents.filter(uploaded_by=user).count()

    return {
        "user":             user,
        "display_name":     user_display_name(user),
        "initials":         user_initials(user),
        "email":            user.email or user.username,
        "role":             role,
        "role_label":       role_label(role),
        "is_owner":         workspace.workspace_owner_id == user.id,
        "is_current_user":  current_user.id == user.id,
        "sessions_count":   sessions_count,
        "questions_count":  questions_count,
        "documents_count":  documents_count,
        "activity_total":   sessions_count + questions_count + documents_count,
        "last_seen":        user.last_login or user.date_joined,
        "status_label":     _("You") if current_user.id == user.id else (_("Active") if user.last_login else _("No login yet")),
    }


def list_member_rows(workspace, current_user):
    """All members + owner (deduped), sorted owner-first then by display name."""
    rows = []
    seen_user_ids = set()

    memberships = WorkspaceMembership.objects.filter(workspace=workspace).select_related("user")
    for membership in memberships:
        user = membership.user
        role = "owner" if workspace.workspace_owner_id == user.id else (membership.role or "member")
        rows.append(build_member_row(workspace, user, role, current_user))
        seen_user_ids.add(user.id)

    if workspace.workspace_owner and workspace.workspace_owner_id not in seen_user_ids:
        rows.append(build_member_row(workspace, workspace.workspace_owner, "owner", current_user))

    rows.sort(key=lambda row: (0 if row["is_owner"] else 1, row["display_name"].lower()))
    return rows


# ---------------------------------------------------------------------------
# Invitation flow — return result tuples (ok, message_text) so views can flash.
# Errors are conditions, not exceptions, because they have user-facing copy.
# ---------------------------------------------------------------------------
def invite_member_by_email(workspace, inviter, email, role):
    """
    Create a pending invitation for `email`. Returns one of:
      ("ok",         "Invitation sent to ...")
      ("forbidden",  "...")
      ("not_found",  "...")
      ("duplicate",  "...")
    """
    if not can_manage_members(workspace, inviter):
        return "forbidden", _("You don't have permission to invite members.")

    if not email:
        return "missing_email", _("Enter the member email address.")

    if role not in MANAGEABLE_ROLES:
        role = "member"

    User = get_user_model()
    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        return "not_found", _("No account was found for that email.")

    if user.id == workspace.workspace_owner_id or WorkspaceMembership.objects.filter(
        workspace=workspace, user=user
    ).exists():
        return "already_member", _("That user is already in this workspace.")

    existing_pending = WorkspaceInvitation.objects.filter(
        workspace=workspace,
        invited_user=user,
        status=WorkspaceInvitation.STATUS_PENDING,
    ).first()
    if existing_pending:
        return "duplicate", _("{name} already has a pending invitation.").format(name=user_display_name(user))

    WorkspaceInvitation.objects.create(
        workspace=workspace,
        invited_user=user,
        invited_by=inviter,
        role=role,
        status=WorkspaceInvitation.STATUS_PENDING,
    )
    activity_log.record(workspace=workspace,actor=inviter,action="member.invited",target=user_display_name(user),invited_email=user.email or user.username,role=role,)
    return "ok", _("Invitation sent to {name}.").format(name=user_display_name(user))


def accept_pending_invitation(invite, accepting_user, now):
    """
    Mark `invite` accepted and create the membership row if missing.
    The view is expected to have already verified `invite.invited_user == accepting_user`.
    `now` is passed in so the view's `timezone.now()` stays consistent with the audit row.
    """
    workspace = invite.workspace

    already_member = is_user_in_workspace(workspace, accepting_user)
    if not already_member:
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=accepting_user,
            role=invite.role,
        )
        activity_log.record(workspace=workspace,actor=accepting_user,action="member.joined",target=user_display_name(accepting_user),role=invite.role,)

    invite.status = WorkspaceInvitation.STATUS_ACCEPTED
    invite.responded_at = now
    invite.save(update_fields=["status", "responded_at"])


def reject_pending_invitation(invite, now):
    invite.status = WorkspaceInvitation.STATUS_REJECTED
    invite.responded_at = now
    invite.save(update_fields=["status", "responded_at"])


# ---------------------------------------------------------------------------
# Membership mutations.
# ---------------------------------------------------------------------------
def change_role(workspace, actor, target_user, new_role):
    """
    Change `target_user`'s role inside `workspace`. Returns (status, message)
    so the view can flash the appropriate copy.
    """
    if workspace.workspace_owner_id != actor.id:
        return "forbidden", _("Only the workspace owner can change member roles.")
    if target_user.id == workspace.workspace_owner_id:
        return "owner_locked", _("The workspace owner's role cannot be changed.")
    if new_role not in MANAGEABLE_ROLES:
        return "invalid_role", _("Invalid role.")

    membership = WorkspaceMembership.objects.filter(workspace=workspace, user=target_user).first()
    if membership is None:
        return "not_a_member", _("That user is not a member of this workspace.")
    if membership.role == new_role:
        return "no_change", ""

    previous_role = membership.role
    membership.role = new_role
    membership.save(update_fields=["role"])
    activity_log.record(workspace=workspace,actor=actor,action="member.role_changed",target=user_display_name(target_user),previous_role=previous_role,new_role=new_role,)
    return "ok", _("{name} is now {role}.").format(name=user_display_name(target_user), role=role_label(new_role))


def remove_member_from_workspace(workspace, actor, target_user):
    """Remove `target_user`'s membership. Returns (status, message)."""
    if not can_manage_members(workspace, actor):
        return "forbidden", _("Only workspace owners can remove members.")
    if target_user.id == workspace.workspace_owner_id:
        return "owner_locked", _("The workspace owner cannot be removed.")

    deleted, _del_detail = WorkspaceMembership.objects.filter(workspace=workspace, user=target_user).delete()
    if not deleted:
        return "not_a_member", _("That user is not a member of this workspace.")

    activity_log.record(workspace=workspace,actor=actor,action="member.removed",target=user_display_name(target_user),user_email=target_user.email or target_user.username,)
    return "ok", _("{name} was removed from this workspace.").format(name=user_display_name(target_user))
