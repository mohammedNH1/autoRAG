from django import template

from workspace.models import WorkspaceMembership
from workspace.services import manage_members

register = template.Library()


@register.simple_tag
def can_edit_settings(workspace, user):
    """True when `user` is the workspace owner or an admin member."""
    if workspace is None or user is None or not user.is_authenticated:
        return False
    if workspace.workspace_owner_id == user.id:
        return True
    return WorkspaceMembership.objects.filter(
        workspace=workspace, user=user, role__in=["owner", "admin"],
    ).exists()


@register.simple_tag
def is_basic_member(workspace, user):
    """True when `user` is restricted to chat sessions only."""
    return manage_members.is_basic_member(workspace, user)
