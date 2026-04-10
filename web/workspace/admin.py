

# Register your models here.
# admin.site.register(User)
# admin.site.register(Workspace)
# admin.site.register(WorkspaceMembership)
# admin.site.register(WorkspaceConfig)

from django.contrib import admin
from .models import User, Workspace, WorkspaceMembership, WorkspaceConfig


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("user_id", "name", "email")
    search_fields = ("name", "email")


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