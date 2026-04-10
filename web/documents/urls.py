"""
URL routing for Qdrant integration
"""

from django.urls import path
from . import views

app_name = "documents"

urlpatterns = [
    # Pages
    path("", views.documents_page, name="documents_page"),
    path("text-input/", views.text_input_page, name="text_input_page"),

    # Actions (API-like)
    path("upload/", views.save_file, name="save_file"),
    path("index/", views.index_document_chunk, name="vector_index"),
    path("search/", views.search_documents, name="vector_search"),
    path("<int:document_id>/delete/", views.delete_document, name="vector_delete"),
]