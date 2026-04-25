from django.contrib import admin
from .models import Workspace, WorkspaceMembership, WorkspaceConfig, Session, Message


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("workspace_id", "workspace_name", "workspace_owner", "tokens")
    search_fields = ("workspace_name",)
    list_filter = ("workspace_owner",)


@admin.register(WorkspaceMembership)
class WorkspaceMembershipAdmin(admin.ModelAdmin):
    list_display = ("workspace", "user", "role")
    list_filter = ("role",)


@admin.register(WorkspaceConfig)
class WorkspaceConfigAdmin(admin.ModelAdmin):
    list_display = ("config_id", "workspace", "retrieval_type", "embedding_model")


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ("session_id", "workspace", "user", "title", "created_at")
    list_filter = ("workspace", "user")
    search_fields = ("session_id", "title")
    readonly_fields = ("session_id", "created_at")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("message_id", "session", "sender", "timestamp")
    list_filter = ("sender", "session")
    search_fields = ("text",)
    readonly_fields = ("message_id", "timestamp")
