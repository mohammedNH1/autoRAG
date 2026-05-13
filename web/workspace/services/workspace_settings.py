"""
Workspace settings — general details, RAG config, API key rotation,
delete, leave. Pure business logic; views handle HTTP.
"""

from pipeline.api.keys import generate_api_key, hash_api_key

from workspace.models import WorkspaceMembership
from workspace.services import activity_log


# Form value → backend-expected chunking label. Mirrors the JS chunkingMap
# so the settings page and the questionnaire submit the same canonical
# strings to determine_chunking_strategy.
CHUNKING_FORM_TO_LABEL = {
    "slide_deck":          "slide deck",
    "meeting_notes":       "meeting notes",
    "article":             "article",
    "research_paper":      "research paper",
    "policy":              "policy",
    "books_long_manuals":  "books or long manuals",
    "undecided":           "undecided",
}


# ---------------------------------------------------------------------------
# Permission check.
# ---------------------------------------------------------------------------
def can_edit_settings(workspace, user):
    return (
        workspace.workspace_owner_id == user.id
        or WorkspaceMembership.objects.filter(
            workspace=workspace, user=user, role__in=["owner", "admin"],
        ).exists()
    )


# ---------------------------------------------------------------------------
# General details (name + description).
# ---------------------------------------------------------------------------
def update_general_details(workspace, name, description):
    """
    Validate + apply name/description. Returns (status, message).
    """
    name = (name or "").strip()
    description = (description or "").strip()
    if not name:
        return "missing_name", "Workspace name is required."
    if len(name) > 150:
        return "name_too_long", "Name must be 150 characters or fewer."

    workspace.workspace_name = name
    workspace.workspace_description = description
    workspace.save(update_fields=["workspace_name", "workspace_description"])
    return "ok", "Workspace details updated."


# ---------------------------------------------------------------------------
# RAG config — read raw form values, derive config fields, diff, persist.
# ---------------------------------------------------------------------------
def update_rag_config(workspace, actor, raw_form):
    """
    Apply a new RAG config to `workspace.config`. `raw_form` is a dict of the
    questionnaire field names → string answers from the POST.

    Returns (status, message). Logs `workspace.config_updated` on success
    with a before/after diff so the audit trail can render each change.
    """
    config = getattr(workspace, "config", None)
    if config is None:
        return "no_config", "Workspace has no configuration to edit."

    # Imported lazily — these helpers live in the pipeline app and we don't
    # want an import-time dependency between the two apps' service layers.
    from pipeline.services.questionnaire_mapper import (
        REQUIRED_QUESTIONNAIRE_FIELDS,
        embedding_reranker,
        top_k as _top_k,
        reference as _reference,
        temperature as _temperature,
        top_p as _top_p,
        add_metadata,
        determine_chunking_strategy,
    )

    raw = {f: (raw_form.get(f) or "").strip() for f in REQUIRED_QUESTIONNAIRE_FIELDS}
    if not all(raw.values()):
        missing = [k for k, v in raw.items() if not v]
        return "missing_answers", f"Missing answers: {', '.join(missing)}"

    raw_chunk_form = raw["chunking_strategy"]
    raw["chunking_strategy"] = CHUNKING_FORM_TO_LABEL.get(raw_chunk_form, raw_chunk_form)

    embedding_config = embedding_reranker(raw["language"], raw["use_case"])
    new_values = {
        "embedding_model":   embedding_config["embedding_model"],
        "re_ranker":         embedding_config["reranker_model"],
        "top_k":             _top_k(raw["reference"]),
        "is_citation":       _reference(raw["reference"]),
        "temperature":       _temperature(raw["temperature"]),
        "top_p":             _top_p(raw["top_p"]),
        "metadata_flag":     add_metadata(raw["metadata"]),
        "chunking_strategy": determine_chunking_strategy(raw["chunking_strategy"]),
    }

    changes = [
        {"field": field, "before": getattr(config, field), "after": value}
        for field, value in new_values.items()
        if getattr(config, field) != value
    ]

    for field, value in new_values.items():
        setattr(config, field, value)

    raw["chunking_strategy"] = raw_chunk_form
    config.raw_answers = raw
    config.save()

    if changes:
        activity_log.record(workspace=workspace,actor=actor,action="workspace.config_updated",target=", ".join(c["field"] for c in changes),
            changes=[
                {"field": c["field"], "before": str(c["before"]), "after": str(c["after"])}
                for c in changes
            ],)

    return "ok", "RAG configuration updated. Note: changing embedding or chunking may require re-indexing existing documents."


# ---------------------------------------------------------------------------
# API key — owner-only generation + rotation.
# ---------------------------------------------------------------------------
def rotate_api_key(workspace, actor):
    """
    Generate a new API key, store its SHA-256 hash, and return the raw key.
    The raw key is the *only* time it can be retrieved — callers must surface
    it to the user immediately and never persist it.

    Returns (raw_key, created_at_iso). Raises PermissionError if `actor`
    isn't the workspace owner.
    """
    if workspace.workspace_owner_id != actor.id:
        raise PermissionError("Only the workspace owner can manage the API key.")

    from django.utils import timezone
    is_regeneration = bool(workspace.api_key)

    raw_key = generate_api_key()
    workspace.api_key = hash_api_key(raw_key)
    workspace.api_key_created_at = timezone.now()
    workspace.save(update_fields=["api_key", "api_key_created_at"])

    activity_log.record(workspace=workspace,actor=actor,action="api_key.regenerated" if is_regeneration else "api_key.created",)
    return raw_key, workspace.api_key_created_at.isoformat()


# ---------------------------------------------------------------------------
# Workspace deletion + leaving.
# ---------------------------------------------------------------------------
def delete_workspace_with_confirmation(workspace, actor, confirm_name):
    """
    Owner-only hard delete; `confirm_name` must equal the workspace name
    to guard against accidental clicks. Returns (status, message).
    """
    if workspace.workspace_owner_id != actor.id:
        return "forbidden", "Only the workspace owner can delete this workspace."
    if (confirm_name or "").strip() != (workspace.workspace_name or ""):
        return "bad_confirm", "Confirmation name does not match. Workspace not deleted."

    workspace.delete()
    return "ok", "Workspace deleted."


def leave_workspace_for_user(workspace, leaving_user):
    """
    Remove a non-owner member from a workspace. Returns (status, message).
    """
    from workspace.services.manage_members import user_display_name

    if workspace.workspace_owner_id == leaving_user.id:
        return "forbidden", "Owners cannot leave their own workspace. Delete it instead."

    deleted, _ = WorkspaceMembership.objects.filter(
        workspace=workspace, user=leaving_user,
    ).delete()
    if not deleted:
        return "not_a_member", ""

    activity_log.record(workspace=workspace,actor=leaving_user,action="member.left",target=user_display_name(leaving_user),)
    return "ok", f"You left {workspace.workspace_name or 'this workspace'}."
