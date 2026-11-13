"""Project Django Admin history into the same audit stream as the REST API.

Only fixed event names and object IDs are copied. Admin change messages may
contain user data, so neither their text nor object representations are stored.
"""
import json

from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.db.models.signals import post_save
from django.dispatch import receiver

from .auditing import record_event


class AuditAdminMixin:
    def log_deletions(self, request, queryset):
        entries = super().log_deletions(request, queryset)
        # Django bulk_create skips post_save for multi-object admin deletions.
        if len(entries) > 1:
            for entry in entries:
                admin_audit_event(LogEntry, entry, created=True)
        return entries


@receiver(post_save, sender=LogEntry)
def admin_audit_event(sender, instance, created, **kwargs):
    if not created or not instance.content_type_id:
        return
    model = (instance.content_type.app_label, instance.content_type.model)
    names = {
        ("asset", "asset"): {CHANGE: "asset_updated", DELETION: "asset_deleted"},
        ("asset", "tags"): {ADDITION: "tag_created", CHANGE: "tag_updated", DELETION: "tag_deleted"},
        ("user", "user"): {ADDITION: "account_created", CHANGE: "account_updated", DELETION: "account_deleted"},
        ("auth", "group"): {ADDITION: "permission_changed", CHANGE: "permission_changed", DELETION: "permission_changed"},
    }
    name = names.get(model, {}).get(instance.action_flag)
    if not name:
        return
    if model == ("user", "user") and instance.action_flag == CHANGE:
        try:
            messages = json.loads(instance.change_message)
            fields = {str(field).casefold() for message in messages for field in message.get("changed", {}).get("fields", [])}
        except (ValueError, TypeError, AttributeError):
            fields = set()
        if fields.intersection({"groups", "staff status", "superuser status"}):
            name = "role_changed"
        elif "user permissions" in fields:
            name = "permission_changed"
        elif "active" in fields:
            from .models import User
            active = User.objects.filter(pk=instance.object_id, is_active=True).exists()
            name = "account_enabled" if active else "account_disabled"
    record_event(name, instance.user, resource_id=instance.object_id,
                 resource_type="account" if model == ("user", "user") else None)
