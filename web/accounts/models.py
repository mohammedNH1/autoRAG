from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    image = models.FileField(upload_to='user_profiles/', null=True, blank=True)

    def __str__(self):
        return f"Profile for {self.user_id}"
