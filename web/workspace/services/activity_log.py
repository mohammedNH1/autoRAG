"""
Single entry point for recording workspace audit-trail events.

Views call `record()` with an action slug from `ACTION_LABELS`; the slug
keeps the database column compact and lets us evolve the human-readable
labels without rewriting old rows.
"""

from workspace.models import WorkspaceActivity


# Slug → human-readable label. Slugs are stored verbatim in the DB; labels
# are looked up at render time so re-wording never needs a data migration.
ACTION_LABELS = {
    "document.uploaded":         "Document uploaded",
    "document.deleted":          "Document deleted",
    "member.joined":             "Member joined",
    "member.left":               "Member left",
    "member.removed":            "Member removed",
    "member.invited":            "Member invited",
    "member.role_changed":       "Member role changed",
    "api_key.created":           "API key created",
    "api_key.regenerated":       "API key regenerated",
    "workspace.config_updated":  "Workspace configuration updated",
}


# Friendly field labels used when rendering a config-update diff.
CONFIG_FIELD_LABELS = {
    "embedding_model":    "Embedding model",
    "re_ranker":          "Reranker",
    "top_k":              "Top-K",
    "is_citation":        "Citations",
    "temperature":        "Temperature",
    "top_p":              "Top-P",
    "metadata_flag":      "Show file details",
    "chunking_strategy":  "Chunking strategy",
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
