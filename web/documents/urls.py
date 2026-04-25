"""
URL routing for Qdrant integration
"""

from django.urls import path
from . import views

app_name = "documents"

urlpatterns = [
    # Pages — scoped to a specific workspace
    path("<int:workspace_id>/", views.documents_page, name="documents_page"),
    path("<int:workspace_id>/text-input/", views.text_input_page, name="text_input_page"),

    # Actions (API-like) — workspace_id is carried in the request body
    path("upload/", views.save_file, name="save_file"),
    path("index/", views.index_document_chunk, name="vector_index"),
    path("search/", views.search_documents, name="vector_search"),
    path("delete/", views.delete_document, name="vector_delete"),
]
