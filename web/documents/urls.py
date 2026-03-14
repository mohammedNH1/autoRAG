"""
URL routing for Qdrant integration
"""

from django.urls import path
from . import views

app_name = 'documents'

urlpatterns = [
    path('', views.documents_page, name='documents_page'), #Added by rayan to run the documents page
    path('text-input/', views.text_input_page, name='text_input_page'), #Added by rayan to run the text input page
    path('index/', views.index_document_chunk, name='vector_index'),
    path('search/', views.search_documents, name='vector_search'),
    path('<int:document_id>/', views.delete_document, name='vector_delete'),
]