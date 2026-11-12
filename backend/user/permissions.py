from django.conf import settings
from rest_framework.permissions import BasePermission


def application_role(user):
    if user.is_superuser or user.groups.filter(name="Admin").exists():
        return "Admin"
    if user.groups.filter(name="Editor").exists():
        return "Editor"
    return "Viewer"


def requires_mfa(user):
    # Mandatory for every account, regardless of role or legacy environment policy.
    return True


def admitted_email(email):
    domains = settings.ACCOUNT_ALLOWED_EMAIL_DOMAINS
    return bool(email and (not domains or email.rsplit("@", 1)[-1].lower() in domains))


def account_allowed(user, mfa_verified=False):
    return bool(user.is_active and user.email_verified and admitted_email(user.email)
                and (not (requires_mfa(user) or user.mfa_enabled) or mfa_verified))


class IsApplicationAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user.is_authenticated and application_role(request.user) == "Admin")
