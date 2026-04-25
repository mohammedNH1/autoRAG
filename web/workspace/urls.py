from django.urls import path

from . import views

urlpatterns = [
    path("", views.workspace_list, name="workspace_list"),
    path("create/", views.create_workspace, name="create_workspace"),

    # Chat page — empty state (no active session) and with-session URL.
    path('<int:workspace_id>/', views.chat_page, name='chat_page'),
    path('<int:workspace_id>/chat/<uuid:session_id>/', views.chat_page, name='chat_session'),

    # Session JSON endpoints (workspace-scoped, owner-scoped).
    path('<int:workspace_id>/sessions/', views.list_sessions, name='list_sessions'),
    path('<int:workspace_id>/sessions/create/', views.create_session, name='create_session'),
    path('<int:workspace_id>/sessions/<uuid:session_id>/messages/', views.session_messages, name='session_messages'),
    path('<int:workspace_id>/sessions/<uuid:session_id>/rename/', views.rename_session, name='rename_session'),
    path('<int:workspace_id>/sessions/<uuid:session_id>/delete/', views.delete_session, name='delete_session'),
]
