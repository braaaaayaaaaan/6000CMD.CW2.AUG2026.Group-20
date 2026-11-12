import uuid

from django.db.models import F
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from .models import User


@receiver(m2m_changed, sender=User.groups.through)
def revoke_role_changes(sender, instance, action, reverse, pk_set, **kwargs):
    if action == "pre_clear" and reverse:
        instance._security_member_ids = list(instance.user_set.values_list("pk", flat=True))
    if action not in {"post_add", "post_remove", "post_clear"}:
        return
    if reverse:
        ids = pk_set if action != "post_clear" else getattr(instance, "_security_member_ids", [])
        User.objects.filter(pk__in=ids).update(token_version=F("token_version") + 1, challenge_nonce=uuid.uuid4())
    else:
        User.objects.filter(pk=instance.pk).update(token_version=F("token_version") + 1, challenge_nonce=uuid.uuid4())
        instance.refresh_from_db(fields=["token_version", "challenge_nonce"])
