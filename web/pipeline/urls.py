from django.urls import path
from . import views

# urls.py
urlpatterns = [
    path('submit-answers/', views.questionnaire, name='submit_answers'),
    path('workspace/<int:workspace_id>/', views.initiate_pipeline, name='initiate_pipeline'),
    path('workspace/<int:workspace_id>/query/', views.query_handling, name='query_handling'),
]
