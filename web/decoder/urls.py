
from django.urls import path
from .views import GenerateView, ModelInfoView

app_name = "decoder"

urlpatterns = [
    path("generate/", GenerateView.as_view(),   name="generate"),
    path("info/",     ModelInfoView.as_view(),  name="info"),
]