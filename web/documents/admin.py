from django.contrib import admin

from .models import Document


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display   = ('document_title', 'workspace', 'uploaded_by', 'upload_time', 'file_extension')
    list_filter    = ('workspace', 'upload_time')
    search_fields  = ('document_title',)
    readonly_fields = ('upload_time',)
