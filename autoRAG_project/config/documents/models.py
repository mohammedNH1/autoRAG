from django.db import models
from django.conf import settings
from workspace.models import Workspace

# This method defines the upload path for documents, organizing them by workspace ID making a folder for each workspace.
def document_upload_path(instance, filename):
    return f"documents/workspace_{instance.workspace.id}/{filename}"

# ----------------------
# Document Table
# ----------------------
class Document(models.Model):
    id = models.AutoField(primary_key=True)

    upload_time = models.DateTimeField(auto_now_add=True)
    document_title = models.CharField(max_length=255, blank=True, null=True)
    
    
    
    # We will store the actual document file in this field
    # upload_to parameter will use the document_upload_path method to determine where to save the file.
    file = models.FileField(upload_to=document_upload_path, blank=True, null=True)
    
    # the workspace that “owns” the document
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="documents"
    )
    
    # who uploaded it; 
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_documents"
    )
    
    def __str__(self):
        return f"Document {self.id}"