from rest_framework.permissions import BasePermission, SAFE_METHODS


class AssetPermission(BasePermission):
    """Authenticated readers; only Editors and administrators may write."""

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated and (
                request.method in SAFE_METHODS
                or user.is_staff or user.is_superuser
                or user.groups.filter(name="Editor").exists()
            )
        )
