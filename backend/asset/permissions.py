from rest_framework.permissions import BasePermission, SAFE_METHODS
from user.permissions import application_role


class AssetPermission(BasePermission):
    """Authenticated readers; only Editors and administrators may write."""

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated and (
                request.method in SAFE_METHODS
                or application_role(user) in {"Editor", "Admin"}
            )
        )
