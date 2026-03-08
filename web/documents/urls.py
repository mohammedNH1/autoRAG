"""
URL routing for Qdrant integration
"""

from django.urls import path
from . import views

app_name = 'documents'

urlpatterns = [
    path('index/', views.index_document_chunk, name='vector_index'),
    path('search/', views.search_documents, name='vector_search'),
    path('<int:document_id>/', views.delete_document, name='vector_delete'),  
]