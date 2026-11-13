"""The application's audit sink and synchronous, explainable monitoring rules."""
import hashlib
import ipaddress
import logging
import re
import unicodedata
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone as dt_timezone

from django.db import connection, transaction
from django.db.models import Count

from .models import AuditEvent, SecurityAlert

current_request = ContextVar("audit_request", default=None)

# type -> category, outcome, severity, resource type. Unknown events are rejected.
EVENTS = {
    "login_succeeded": ("authentication", "success", "info", "account"),
    "login_failed": ("authentication", "failure", "medium", "account"),
    "authentication_failed": ("authentication", "failure", "info", "account"),
    "logout": ("authentication", "success", "info", "account"),
    "logout_all": ("authentication", "success", "info", "account"),
    "mfa_verification_succeeded": ("authentication", "success", "info", "account"),
    "mfa_verification_failed": ("authentication", "failure", "medium", "account"),
    "mfa_enabled": ("account", "success", "info", "account"),
    "mfa_removed": ("account", "success", "medium", "account"),
    "mfa_recovery_approved": ("account", "success", "medium", "account"),
    "email_verified": ("account", "success", "info", "account"),
    "password_reset": ("account", "success", "info", "account"),
    "account_created": ("account", "success", "info", "account"),
    "account_updated": ("account", "success", "info", "account"),
    "account_disabled": ("account", "success", "medium", "account"),
    "account_enabled": ("account", "success", "info", "account"),
    "account_deleted": ("account", "success", "medium", "account"),
    "role_changed": ("authorization", "success", "medium", "account"),
    "permission_changed": ("authorization", "success", "medium", "group"),
    "access_denied": ("authorization", "denied", "medium", "operation"),
    "asset_uploaded": ("asset", "success", "info", "asset"),
    "asset_downloaded": ("asset", "success", "info", "asset"),
    "asset_previewed": ("asset", "success", "info", "asset"),
    "asset_replaced": ("asset", "success", "info", "asset"),
    "asset_updated": ("asset", "success", "info", "asset"),
    "asset_deleted": ("asset", "success", "info", "asset"),
    "tag_created": ("management", "success", "info", "tag"),
    "tag_updated": ("management", "success", "info", "tag"),
    "tag_deleted": ("management", "success", "info", "tag"),
    "alert_resolved": ("management", "success", "info", "security_alert"),
    "account_email_delivery_failed": ("account", "failure", "info", ""),
    "account_email_queue_full": ("account", "failure", "info", ""),
}

# All thresholds and window lengths live here. Detection never changes accounts.
RULES = {
    "login_failed": {"type": "repeated_failed_login", "threshold": 5, "seconds": 600,
                     "severity": "medium", "description": "Repeated failed sign in attempts were detected for this account"},
    "asset_downloaded": {"type": "bulk_download", "threshold": 20, "seconds": 300,
                         "severity": "high", "description": "Suspicious download activity was detected for this user"},
    "access_denied": {"type": "repeated_access_denial", "threshold": 5, "seconds": 600,
                      "severity": "medium", "description": "Repeated access denials were detected for this user"},
}


def identifier(value):
    # Django's username mechanism is case sensitive and NFKC normalized.
    value = unicodedata.normalize("NFKC", value) if isinstance(value, str) else ""
    return value if len(value) <= 150 and re.fullmatch(r"[\w.@+-]+", value) else ""


def safe_metadata(name, values):
    # Typed allowlists deliberately discard arbitrary bodies, URLs and credentials.
    result = {}
    for key in ("version_no", "version_count", "response_status", "bytes_served"):
        value = (values or {}).get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            result[key] = value
    if name == "access_denied":
        method = (values or {}).get("method")
        if method in {"GET", "HEAD", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"}:
            result["method"] = method
    if name == "role_changed":
        for key in ("previous_role", "role"):
            value = (values or {}).get(key)
            if value in {"Viewer", "Editor", "Admin"}:
                result[key] = value
    return result


def subject_for(name, actor, account_identifier):
    subject = account_identifier if name == "login_failed" else str(actor.pk) if actor else ""
    return hashlib.sha256(subject.encode()).hexdigest() if subject else ""


def lock_subject(name, subject):
    # Serialize concurrent threshold checks on PostgreSQL, including unknown logins.
    # SQLite test writes are serialized by the database itself.
    if connection.vendor == "postgresql" and subject:
        key = int.from_bytes(hashlib.sha256((name + subject).encode()).digest()[:8], "big", signed=True)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])


def record_event(name, user=None, target=None, *, request=None, account_identifier="", resource_id="", resource_type=None, metadata=None):
    category, outcome, severity, default_resource_type = EVENTS[name]
    resource_type = resource_type if resource_type in {"account", "group"} else default_resource_type
    request = request if request is not None else current_request.get()
    if user is None and request is not None:
        candidate = getattr(request, "user", None)
        user = candidate if candidate is not None and candidate.is_authenticated else None
    account_identifier = identifier(account_identifier)
    subject = subject_for(name, user, account_identifier) if name in RULES else ""
    address = request.META.get("REMOTE_ADDR") if request is not None else None
    try:
        address = str(ipaddress.ip_address(address))
    except ValueError:
        address = None
    # REMOTE_ADDR only. Do not trust spoofable forwarded client headers.
    agent = request.META.get("HTTP_USER_AGENT", "") if request is not None else ""
    agent = re.sub(r"[\x00-\x1f\x7f]", "", agent)[:512]
    with transaction.atomic():
        lock_subject(name, subject)
        event = AuditEvent.objects.create(
            actor=user, actor_reference=str(user.pk) if user else "", account_identifier=account_identifier, event_type=name, category=category,
            resource_type=resource_type, resource_id=str(target.pk if target is not None else resource_id)[:100],
            ip_address=address, user_agent=agent, outcome=outcome, severity=severity,
            metadata=safe_metadata(name, metadata),
        )
        if subject:
            detect(event, subject)
    # Preserve the existing safe console sink, emitted once per structured event.
    logging.getLogger("dam.audit").info("event=%s actor=%s resource=%s", name, user.pk if user else "anonymous", event.resource_id)
    return event


def detect(event, subject):
    rule = RULES[event.event_type]
    start = event.timestamp - timedelta(seconds=rule["seconds"])
    events = AuditEvent.objects.filter(event_type=event.event_type, timestamp__gte=start, timestamp__lte=event.timestamp)
    if event.event_type == "login_failed":
        events = events.filter(account_identifier=event.account_identifier)
    else:
        events = events.filter(actor=event.actor, outcome="success" if event.event_type == "asset_downloaded" else "denied")
    count = events.aggregate(count=Count("id"))["count"]
    if count < rule["threshold"]:
        return
    # Rolling detection, fixed UTC deduplication buckets. At most one alert per
    # subject/rule/bucket, even if resolved early or requests arrive concurrently.
    bucket = int(event.timestamp.timestamp()) // rule["seconds"] * rule["seconds"]
    alert, created = SecurityAlert.objects.get_or_create(
        alert_type=rule["type"], subject_key=subject,
        bucket_start=datetime.fromtimestamp(bucket, tz=dt_timezone.utc),
        defaults={"affected_user": event.actor, "account_identifier": event.account_identifier,
                  "severity": rule["severity"], "description": rule["description"], "event_count": count,
                  "window_seconds": rule["seconds"], "window_started_at": start,
                  "last_detected_at": event.timestamp, "metadata": {"threshold": rule["threshold"], "event_type": event.event_type}},
    )
    if not created:
        SecurityAlert.objects.filter(pk=alert.pk).update(event_count=count, window_started_at=start, last_detected_at=event.timestamp)


def exception_handler(exc, context):
    from rest_framework.exceptions import PermissionDenied
    from rest_framework.views import exception_handler as drf_handler

    response = drf_handler(exc, context)
    request = context["request"]
    if isinstance(exc, PermissionDenied) and request.user.is_authenticated:
        match = request.resolver_match
        # Store the known route name rather than a URL, query string or body.
        record_event("access_denied", request.user, request=request,
                     resource_id=match.view_name if match else "protected_operation",
                     metadata={"method": request.method})
    return response
