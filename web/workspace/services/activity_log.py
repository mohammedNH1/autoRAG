"""
Single entry point for recording workspace audit-trail events.

Views call `record()` with an action slug from `ACTION_LABELS`; the slug
keeps the database column compact and lets us evolve the human-readable
labels without rewriting old rows.
"""

from django.utils.translation import gettext_lazy as _

from workspace.models import WorkspaceActivity


# Slug → human-readable label. Slugs are stored verbatim in the DB; labels
# are looked up at render time so re-wording never needs a data migration.
ACTION_LABELS = {
    "document.uploaded":         _("Document uploaded"),
    "document.deleted":          _("Document deleted"),
    "member.joined":             _("Member joined"),
    "member.left":               _("Member left"),
    "member.removed":            _("Member removed"),
    "member.invited":            _("Member invited"),
    "member.role_changed":       _("Member role changed"),
    "api_key.created":           _("API key created"),
    "api_key.regenerated":       _("API key regenerated"),
    "workspace.config_updated":  _("Workspace configuration updated"),
}


# Friendly field labels used when rendering a config-update diff.
CONFIG_FIELD_LABELS = {
    "embedding_model":    _("Embedding model"),
    "re_ranker":          _("Reranker"),
    "top_k":              _("Top-K"),
    "is_citation":        _("Citations"),
    "temperature":        _("Temperature"),
    "top_p":              _("Top-P"),
    "metadata_flag":      _("Show file details"),
    "chunking_strategy":  _("Chunking strategy"),
}


def record(workspace, actor, action, target="", **metadata):
    """
    Append one row to the audit trail.

    `actor` may be None for system-initiated events. Extra keyword args
    are stored in the `metadata` JSON column so action-specific details
    (role, change diff, etc.) can be rendered later.
    """
    if action not in ACTION_LABELS:
        raise ValueError(f"Unknown audit action: {action!r}")
    return WorkspaceActivity.objects.create(
        workspace=workspace,
        actor=actor,
        action=action,
        target=target or "",
        metadata=metadata or {},
    )
