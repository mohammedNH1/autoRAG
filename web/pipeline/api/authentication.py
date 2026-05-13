"""
DRF authentication class for workspace API keys.

The external API does not authenticate a user — it authenticates a
*workspace*. We attach the resolved workspace to `request.workspace`
so the view can run the RAG pipeline against it without any further
lookup.
"""

from rest_framework import authentication, exceptions

from workspace.models import Workspace

from .keys import hash_api_key, looks_like_api_key


HEADER = "HTTP_X_API_KEY"


class WorkspaceAPIKeyAuthentication(authentication.BaseAuthentication):
    """Reads `X-API-Key`, hashes it, and looks up the owning workspace."""

    def authenticate(self, request):
        raw_key = request.META.get(HEADER, "").strip()
        if not raw_key:
            # No header → let DRF treat the request as unauthenticated; the
            # view's permission layer turns that into a 401.
            return None

        if not looks_like_api_key(raw_key):
            raise exceptions.AuthenticationFailed("Invalid API key format.")

        digest = hash_api_key(raw_key)
        workspace = Workspace.objects.filter(api_key=digest).first()
        if workspace is None:
            raise exceptions.AuthenticationFailed("Invalid API key.")

        # DRF expects (user, auth). We have no user — stash the workspace as
        # the `auth` half and also bolt it onto the request for convenience.
        request.workspace = workspace
        return (None, workspace)

    def authenticate_header(self, request):
        # Causes DRF to return 401 (rather than 403) when no header is sent.
        return "X-API-Key"
