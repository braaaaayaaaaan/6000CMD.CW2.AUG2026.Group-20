from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.crypto import salted_hmac
import uuid

# Create your models here.
class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    token_version = models.PositiveIntegerField(default=0, editable=False)
    email_verified = models.BooleanField(default=False, editable=False)
    verification_nonce = models.UUIDField(default=uuid.uuid4, editable=False)
    challenge_nonce = models.UUIDField(default=uuid.uuid4, editable=False)
    # Fernet ciphertext only. Recovery codes use Django's password hashers.
    mfa_secret = models.TextField(blank=True, editable=False)
    mfa_pending_secret = models.TextField(blank=True, editable=False)
    mfa_pending_at = models.DateTimeField(null=True, editable=False)
    mfa_last_step = models.BigIntegerField(default=-1, editable=False)
    mfa_recovery_hashes = models.JSONField(default=list, editable=False)
    auth_failures = models.PositiveIntegerField(default=0, editable=False)
    auth_locked_until = models.DateTimeField(null=True, editable=False)

    @property
    def mfa_enabled(self):
        return bool(self.mfa_secret)

    def save(self, *args, **kwargs):
        security_changed = False
        if not self._state.adding:
            fields = {"email", "email_verified", "is_active", "is_staff", "is_superuser", "password"}
            old = type(self).objects.filter(pk=self.pk).values(*fields, "token_version").first()
            if old:
                self.token_version = max(self.token_version, old["token_version"])
            selected = fields if kwargs.get("update_fields") is None else fields.intersection(kwargs["update_fields"])
            changed = old and any(old[field] != getattr(self, field) for field in selected)
            if changed:
                security_changed = True
                extra = {"token_version", "challenge_nonce"}
                self.token_version = max(self.token_version, old["token_version"] + 1)
                self.challenge_nonce = uuid.uuid4()
                if "email" in selected and old["email"].lower() != self.email.lower():
                    self.email_verified = False
                    self.verification_nonce = uuid.uuid4()
                    extra.update({"email_verified", "verification_nonce"})
                if kwargs.get("update_fields") is not None:
                    kwargs["update_fields"] = set(kwargs["update_fields"]) | extra
        super().save(*args, **kwargs)
        if security_changed:
            # Also deny a Django Admin session whose hash Django has just refreshed.
            self.account_sessions.update(revoked=True)

    def _get_session_auth_hash(self, secret=None):
        # Reuse Django's session hash validation, including secret-key fallback.
        value = super()._get_session_auth_hash(secret=secret)
        return salted_hmac("user.security.session", f"{value}:{self.token_version}",
                           secret=secret, algorithm="sha256").hexdigest()


class AccountSession(models.Model):
    """Revocation record for an existing SimpleJWT/Django authenticated session."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="account_sessions")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked = models.BooleanField(default=False)
    mfa_verified = models.BooleanField(default=False)


class EmailIdentity(models.Model):
    # A new table avoids a destructive uniqueness migration over legacy emails.
    user = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True)
    email = models.EmailField(unique=True)


class AuditEvent(models.Model):
    """Selected application events. No request payloads or authentication material."""

    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_events")
    actor_reference = models.CharField(max_length=36, blank=True)
    account_identifier = models.CharField(max_length=150, blank=True)
    event_type = models.CharField(max_length=64, db_index=True)
    category = models.CharField(max_length=32, db_index=True)
    resource_type = models.CharField(max_length=32, blank=True)
    resource_id = models.CharField(max_length=100, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    outcome = models.CharField(max_length=16, default="success")
    severity = models.CharField(max_length=16, default="info")
    metadata = models.JSONField(default=dict)

    class Meta:
        ordering = ["-timestamp", "-id"]
        indexes = [
            models.Index(fields=["event_type", "account_identifier", "timestamp"], name="audit_account_window"),
            models.Index(fields=["event_type", "actor", "timestamp"], name="audit_actor_window"),
        ]


class SecurityAlert(models.Model):
    alert_type = models.CharField(max_length=64)
    affected_user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="security_alerts")
    account_identifier = models.CharField(max_length=150, blank=True)
    # Internal hash identifies a subject without using raw client input as a key.
    subject_key = models.CharField(max_length=64)
    bucket_start = models.DateTimeField()
    severity = models.CharField(max_length=16)
    description = models.CharField(max_length=300)
    event_count = models.PositiveIntegerField()
    window_seconds = models.PositiveIntegerField()
    window_started_at = models.DateTimeField()
    first_detected_at = models.DateTimeField(auto_now_add=True)
    last_detected_at = models.DateTimeField()
    status = models.CharField(max_length=16, choices=[("open", "Open"), ("resolved", "Resolved")], default="open", db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="resolved_security_alerts")
    metadata = models.JSONField(default=dict)

    class Meta:
        ordering = ["-last_detected_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["alert_type", "subject_key", "bucket_start"], name="unique_security_alert_bucket")]
