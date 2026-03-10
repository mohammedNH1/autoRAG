from django.urls import path
from . import views

# urls.py
urlpatterns = [
    path('questionnaire/', views.questionnaire_page, name='questionnaire_page'), #Added by rayan to run the questionnaire page
    path('submit-answers/', views.questionnaire, name='submit_answers'),
    path('workspace/<int:workspace_id>/', views.initiate_pipeline, name='initiate_pipeline'),
    path('workspace/<int:workspace_id>/query/', views.query_handling, name='query_handling'),
]
