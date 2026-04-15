from django.urls import path
from . import views

# urls.py

urlpatterns = [
    path('questionnaire/', views.questionnaire_page, name='questionnaire_page'),
    path('submit-answers/', views.questionnaire, name='submit_answers'),
    path('api/chat/sessions', views.create_session, name='create_session'),
    path('api/chat/send', views.query_handling, name='query_handling'),
]
# path('workspace/<int:workspace_id>/query/', views.query_handling, name='query_handling'),