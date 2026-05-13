
from django.db import models
from django.conf import settings
import uuid


# ----------------------
# Main Workspace Table
# ----------------------
class Workspace(models.Model):
    workspace_id = models.AutoField(primary_key=True)

    workspace_name = models.CharField(max_length=150, null=True, blank=True)
    workspace_description = models.TextField(blank=True, default="")

    workspace_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_workspaces"
    )

    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="WorkspaceMembership",
        related_name="workspaces"
    )

    tokens = models.IntegerField(default=0)
    collection_id = models.CharField(max_length=255, blank=True, null=True)

    # SHA-256 hex digest of the raw API key (64 chars). The raw key is shown
    # once at generation and never stored. Indexed for O(log n) lookup from
    # the X-API-Key header during external API authentication.
    api_key = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    api_key_created_at = models.DateTimeField(null=True, blank=True)

    workspace_image = models.FileField(
        upload_to='workspace_images/',
        null=True,
        blank=True,
    )

    def __str__(self):
        return self.workspace_name or f"Workspace {self.workspace_id}"


# ----------------------
# Through Table (M2M + role)
# ----------------------
class WorkspaceMembership(models.Model):
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )

    role = models.CharField(max_length=50)

    class Meta:
        unique_together = ('workspace', 'user')

    def __str__(self):
        return f"{self.user} in {self.workspace.workspace_name} as {self.role}"


# ----------------------
# Workspace Invitation
# ----------------------
class WorkspaceInvitation(models.Model):
    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_REJECTED, "Rejected"),
    ]

    invitation_id = models.AutoField(primary_key=True)

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="invitations",
    )

    invited_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_invitations",
    )

    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_invitations",
    )

    role = models.CharField(max_length=50, default="member")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Invite {self.invitation_id} for {self.invited_user} → {self.workspace} ({self.status})"


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
    is_citation  = models.BooleanField(default=False)
    metadata_flag = models.BooleanField(default=False)

    # LLM parameters
    temperature = models.FloatField(default=0.7)
    top_p = models.FloatField(default=1.0)
    top_k = models.IntegerField(default=5)

    # Raw questionnaire answers — kept so the Settings page can prefill the
    # RAG form without lossy reverse-mapping from derived numeric values.
    raw_answers = models.JSONField(null=True, blank=True)

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
        settings.AUTH_USER_MODEL,
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
