from django.db import models
from django.contrib.auth.models import AbstractUser
import uuid

# Create your models here.
class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    token_version = models.PositiveIntegerField(default=0, editable=False)
