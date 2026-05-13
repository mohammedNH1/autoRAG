"""
Chat session CRUD — list, create, rename, delete, fetch messages.

These functions operate on domain objects; the view layer handles HTTP.
"""

from workspace.models import Session


# ---------------------------------------------------------------------------
# Lookup helpers.
# ---------------------------------------------------------------------------
def get_user_session(workspace, user, session_id):
    """Return the session if it belongs to this user in this workspace, else None."""
    return Session.objects.filter(
        workspace=workspace,
        user=user,
        session_id=session_id,
    ).first()


def list_user_sessions(workspace, user):
    """All sessions a user owns inside `workspace`, newest first."""
    return Session.objects.filter(workspace=workspace, user=user).order_by("-created_at")


# ---------------------------------------------------------------------------
# Mutations.
# ---------------------------------------------------------------------------
def create_blank_session(workspace, user):
    """Make a new empty 'New Session' for the user."""
    return Session.objects.create(workspace=workspace, user=user, title="New Session")


def rename(session, title):
    """
    Validate + apply a new title. Returns (status, message_or_title).
    """
    title = (title or "").strip()
    if not title:
        return "missing_title", "Title is required"
    if len(title) > 150:
        return "title_too_long", "Title too long"

    session.title = title
    session.save(update_fields=["title"])
    return "ok", session.title


def delete(session):
    session.delete()


# ---------------------------------------------------------------------------
# Serialization for JSON endpoints.
# ---------------------------------------------------------------------------
def serialize_session_summary(session, url):
    return {
        "session_id": str(session.session_id),
        "title":      session.title,
        "created_at": session.created_at.isoformat(),
        "url":        url,
    }


def serialize_messages(session):
    return [
        {
            "message_id": str(m.message_id),
            "sender":     m.sender,
            "text":       m.text,
            "timestamp":  m.timestamp.isoformat(),
        }
        for m in session.messages.all()
    ]
