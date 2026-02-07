from django.urls import path
from . import views

# urls.py
urlpatterns = [
    path('submit-answers/', views.questionnaire, name='submit_answers'),
]
