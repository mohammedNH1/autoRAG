from django.shortcuts import render

from workspace.models import Workspace


def chat(request):
    """
    Render the main chat workspace.

    For now this uses static example data. Once the backend API and
    persistence are defined, these values can be populated from the
    database or an MCP service.
    """
    workspace_name = "AutoRAG Workspace"

    sessions = [
        {
            "id": "s_1",
            "title": "Refund Process – Step-by-Step Procedu...",
            "is_active": True,
        },
        {
            "id": "s_2",
            "title": "Compare 2023 vs 2024 Pricing Model C...",
            "is_active": False,
        },
        {
            "id": "s_3",
            "title": "Summarize the new pricing changes",
            "is_active": False,
        },
        {
            "id": "s_4",
            "title": "Reset company email password",
            "is_active": False,
        },
        {
            "id": "s_5",
            "title": "Sick Leave Rules",
            "is_active": False,
        },
        {
            "id": "s_6",
            "title": "Security Incident Reporting",
            "is_active": False,
        },
        {
            "id": "s_7",
            "title": "Integration Requirements",
            "is_active": False,
        },
        {
            "id": "s_8",
            "title": "Change Request Policy",
            "is_active": False,
        },
        {
            "id": "s_9",
            "title": "Vendor Onboarding Checklist",
            "is_active": False,
        },
        {
            "id": "s_10",
            "title": "Remote Work Agreement Clause Check",
            "is_active": False,
        },
    ]

    active_session = next((s for s in sessions if s.get("is_active")), sessions[0])

    context = {
        "workspace_name": workspace_name,
        "session_name": active_session["title"],
        "sessions": sessions,
        #Added by rayan
        "workspace_id": 1,
        "api_base_url": "",
        #end of added by rayan
    }

    return render(request, "chat.html", context)
from pipeline.services.pipeline_registry import get_pipeline

def chat_page(request, workspace_id):
    workspace = Workspace.objects.get(workspace_id=workspace_id)
    get_pipeline(workspace_id, workspace.config)
    return render(request, "chat.html", {"workspace_id": workspace_id})