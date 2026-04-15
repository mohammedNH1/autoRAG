
from django.db import models
import uuid

# ----------------------
# User Table
# ----------------------
class User(models.Model):
    user_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=255)  # already hashed before saving

    def __str__(self):
        return self.name


# ----------------------
# Main Workspace Table
# ----------------------
class Workspace(models.Model):
    workspace_id = models.AutoField(primary_key=True)

    workspace_name = models.CharField(max_length=150, null=True, blank=True)


    workspace_owner = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_workspaces"
    )

    users = models.ManyToManyField(
        User,
        through="WorkspaceMembership",
        related_name="workspaces"
    )

    tokens = models.IntegerField(default=0)
    collection_id = models.CharField(max_length=255, blank=True, null=True)
    api_key = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return self.workspace_name


# ----------------------
# Through Table (M2M + role)
# ----------------------
class WorkspaceMembership(models.Model):
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE
    )

    role = models.CharField(max_length=50) 

    class Meta:
        unique_together = ('workspace', 'user')

    def __str__(self):
        return f"{self.user.name} in {self.workspace.workspace_name} as {self.role}"


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
    

# ----------------------
# Session Table
# ----------------------
class Session(models.Model):
    

    session_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="sessions"
    )
    
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sessions"
    )
    
    title = models.CharField(max_length=150, default="New Session")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Session {self.session_id} in Workspace {self.workspace.workspace_id}"


# ----------------------
# Message Table
# ----------------------
class Message(models.Model):
    class Meta:
        ordering = ['timestamp']

    SENDER_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
    ]

    message_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    session = models.ForeignKey(
        Session,
        on_delete=models.CASCADE,
        related_name="messages"
    )
    
    sender = models.CharField(max_length=10, choices=SENDER_CHOICES)
    text = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.sender} message in Session {self.session.session_id}"    