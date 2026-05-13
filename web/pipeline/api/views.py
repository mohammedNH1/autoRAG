"""
External `/api/v1/` views. Authentication is per-workspace via the
`X-API-Key` header — see `authentication.WorkspaceAPIKeyAuthentication`.
"""

from rest_framework import status
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from pipeline.services.query_service import run_query

from .authentication import WorkspaceAPIKeyAuthentication
from .serializers import QueryRequestSerializer


SNIPPET_MAX_CHARS = 240


class HasWorkspaceAPIKey(BasePermission):
    """Authenticate() attaches `request.workspace`; this just enforces it."""

    message = "Missing or invalid API key."

    def has_permission(self, request, view):
        return getattr(request, "workspace", None) is not None


class QueryView(APIView):
    """
    POST /api/v1/query

    Headers:
        X-API-Key: autorag_xxxxx

    Body:
        { "question": "..." }

    Response:
        { "answer": "...", "citations": [{document, page, snippet}, ...] }
    """

    authentication_classes = [WorkspaceAPIKeyAuthentication]
    permission_classes     = [HasWorkspaceAPIKey]

    def post(self, request):
        serializer = QueryRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = serializer.validated_data["question"]

        workspace = request.workspace
        if not hasattr(workspace, "config"):
            return Response(
                {"error": "Workspace is not configured yet."},
                status=status.HTTP_409_CONFLICT,
            )

        result = run_query(workspace, question)

        citations = []
        if result.is_citation:
            for payload in result.sources:
                snippet = (payload.get("text") or "").strip().replace("\n", " ")
                if len(snippet) > SNIPPET_MAX_CHARS:
                    snippet = snippet[: SNIPPET_MAX_CHARS - 1].rstrip() + "…"
                citations.append({
                    "document": payload.get("document_title") or payload.get("source", "Unknown"),
                    "page":     str(payload.get("section") or payload.get("page", "")),
                    "snippet":  snippet,
                })

        return Response({"answer": result.answer, "citations": citations})
