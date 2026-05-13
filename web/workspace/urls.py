from django.urls import path

from . import views

urlpatterns = [
    path("", views.workspace_list, name="workspace_list"),
    path("create/", views.create_workspace, name="create_workspace"),

    # Invitations (current user's pending list + accept/reject).
    path("invitations/", views.list_invitations, name="list_invitations"),
    path("invitations/<int:invitation_id>/accept/", views.accept_invitation, name="accept_invitation"),
    path("invitations/<int:invitation_id>/reject/", views.reject_invitation, name="reject_invitation"),

    # Chat page — empty state (no active session) and with-session URL.
    path('<int:workspace_id>/', views.chat_page, name='chat_page'),
    path('<int:workspace_id>/chat/<uuid:session_id>/', views.chat_page, name='chat_session'),

    # Dashboard page — analytics + audit trail (empty state when no sessions).
    path('<int:workspace_id>/dashboard/', views.dashboard, name='workspace_dashboard'),
    path('<int:workspace_id>/members/', views.members, name='workspace_members'),
    path('<int:workspace_id>/members/add/', views.add_member, name='workspace_add_member'),
    path('<int:workspace_id>/members/<int:user_id>/remove/', views.remove_member, name='workspace_remove_member'),
    path('<int:workspace_id>/members/<int:user_id>/role/', views.change_member_role, name='workspace_change_member_role'),

    # Settings
    path('<int:workspace_id>/settings/', views.workspace_settings, name='workspace_settings'),
    path('<int:workspace_id>/settings/general/', views.update_workspace_general, name='workspace_settings_general'),
    path('<int:workspace_id>/settings/config/', views.update_workspace_config, name='workspace_settings_config'),
    path('<int:workspace_id>/settings/delete/', views.delete_workspace, name='workspace_settings_delete'),
    path('<int:workspace_id>/settings/leave/', views.leave_workspace, name='workspace_settings_leave'),
    path('<int:workspace_id>/settings/api-key/generate/', views.generate_workspace_api_key, name='workspace_generate_api_key'),

    # Session JSON endpoints (workspace-scoped, owner-scoped).
    path('<int:workspace_id>/sessions/', views.list_sessions, name='list_sessions'),
    path('<int:workspace_id>/sessions/create/', views.create_session, name='create_session'),
    path('<int:workspace_id>/sessions/<uuid:session_id>/messages/', views.session_messages, name='session_messages'),
    path('<int:workspace_id>/sessions/<uuid:session_id>/rename/', views.rename_session, name='rename_session'),
    path('<int:workspace_id>/sessions/<uuid:session_id>/delete/', views.delete_session, name='delete_session'),
]
