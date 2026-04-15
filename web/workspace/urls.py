from django.urls import path

from . import views

urlpatterns = [
    path("chat/", views.chat, name="workspace_chat"),
     path('<int:workspace_id>/', views.chat_page, name='chat_page'),
]


