from django.contrib.auth.models import Group
from django.db import transaction
from rest_framework import permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from .models import User
from .permissions import IsApplicationAdmin, application_role
from .security import event
from .serializers import UserSerializer, GroupSerializer


class IsAdminOrSelf(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        return application_role(request.user) == "Admin" or obj == request.user


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.order_by("-date_joined", "id").prefetch_related("groups")
    serializer_class = UserSerializer

    def get_permissions(self):
        if self.action == "create":
            return [permissions.AllowAny()]
        if self.action in {"list", "role", "status"}:
            return [IsApplicationAdmin()]
        return [IsAdminOrSelf()]

    def get_authenticators(self):
        # Signup does not depend on a stale cookie from a previous browser login.
        if self.request.method == "POST" and self.request.path_info.rstrip("/") == "/users":
            return []
        return super().get_authenticators()

    def create(self, request, *args, **kwargs):
        from rest_framework.authentication import SessionAuthentication
        SessionAuthentication().enforce_csrf(request)
        return super().create(request, *args, **kwargs)

    def get_throttles(self):
        throttles = super().get_throttles()
        if self.action == "create":
            self.throttle_scope = "signup"
            throttles.append(ScopedRateThrottle())
        return throttles

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.select_for_update() if self.action in {"update", "partial_update", "role", "status"} else queryset

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return super().update(request, *args, **kwargs)

    @action(detail=True, methods=["patch"])
    @transaction.atomic
    def role(self, request, pk=None):
        user = self.get_object()
        value = serializers.ChoiceField(choices=["Viewer", "Editor", "Admin"]).run_validation(request.data.get("role"))
        group = Group.objects.get(name=value)
        # Retain unrelated Django groups/model permissions; replace application roles.
        user.groups.remove(*user.groups.filter(name__in=["Viewer", "Editor", "Admin"]))
        user.groups.add(group)
        event("role_changed", request.user, target=user)
        return Response({"id": str(user.pk), "role": value})

    @action(detail=True, methods=["patch"])
    @transaction.atomic
    def status(self, request, pk=None):
        user = self.get_object()
        user.is_active = serializers.BooleanField().run_validation(request.data.get("is_active"))
        user.save(update_fields=["is_active"])
        event("account_status_changed", request.user, target=user)
        return Response({"id": str(user.pk), "is_active": user.is_active})


class GroupViewSet(viewsets.ReadOnlyModelViewSet):
    # Django Admin remains the place to manage model permissions and group names.
    queryset = Group.objects.order_by("name", "id")
    serializer_class = GroupSerializer
    permission_classes = [IsApplicationAdmin]
