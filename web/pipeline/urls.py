from django.urls import path
from . import views

urlpatterns = [
    path('questionnaire/', views.questionnaire_page, name='questionnaire_page'),
    path('submit-answers/', views.questionnaire, name='submit_answers'),
    path('api/chat/send', views.query_handling, name='query_handling'),
]
