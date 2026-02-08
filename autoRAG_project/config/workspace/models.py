from django.db import models

# Create your models here.
# workspace/models.py
from django.db import models

# ----------------------
# Main Workspace Table
# ----------------------
class Workspace(models.Model):
    workspace_id = models.AutoField(primary_key=True)
    tokens = models.IntegerField(default=0)
    collection_id = models.CharField(max_length=255, blank=True, null=True)
    api_key = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"Workspace {self.workspace_id}"


# ----------------------
# Weak Entity: Config
# ----------------------
class WorkspaceConfig(models.Model):
    config_id = models.AutoField(primary_key=True)
    
    # One-to-one relationship with Workspace
    workspace = models.OneToOneField(
        Workspace,
        on_delete=models.CASCADE,  # if workspace deleted, config deleted
        related_name="config"
    )
    
    # RAG configuration fields
    retrieval_type = models.CharField(max_length=50)
    re_ranker = models.CharField(max_length=50)
    embedding_model = models.CharField(max_length=100)
    chunking_strategy = models.CharField(max_length=50)
    distance_metric = models.CharField(max_length=50)
    
    # LLM parameters
    temperature = models.FloatField(default=0.7)
    top_p = models.FloatField(default=1.0)
    top_k = models.IntegerField(default=5)

    def __str__(self):
        return f"Config {self.config_id} for Workspace {self.workspace.workspace_id}"
