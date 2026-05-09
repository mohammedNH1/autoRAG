import os
from django.db import models
from django.conf import settings
from workspace.models import Workspace


def document_upload_path(instance, filename):
    return f"documents/workspace_{instance.workspace_id}/{filename}"


class Document(models.Model):
    upload_time    = models.DateTimeField(auto_now_add=True)
    document_title = models.CharField(max_length=255, blank=True, null=True)
    file           = models.FileField(upload_to=document_upload_path, blank=True, null=True)
    workspace      = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_documents",
    )

    @property
    def file_extension(self) -> str:
        if self.file:
            _, ext = os.path.splitext(self.file.name)
            return ext.lower().lstrip('.')
        return ''

    def __str__(self):
        return self.document_title or f"Document {self.pk}"
