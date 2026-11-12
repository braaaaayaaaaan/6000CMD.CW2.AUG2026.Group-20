from django.contrib.auth.models import Group
from django.db import transaction
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from datetime import timedelta
import uuid
from rest_framework import permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from .models import User, AccountSession
from .permissions import IsApplicationAdmin, application_role
from .security import event, verify_sensitive_password
from .serializers import UserSerializer, GroupSerializer


class IsAdminOrSelf(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        return application_role(request.user) == "Admin" or obj == request.user


@method_decorator(sensitive_post_parameters(), name="dispatch")
class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.order_by("-date_joined", "id").prefetch_related("groups")
    serializer_class = UserSerializer

    def get_permissions(self):
        if self.action == "create":
            return [permissions.AllowAny()]
        if self.action in {"list", "role", "status", "recover_mfa"}:
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
        elif self.action in {"update", "partial_update", "recover_mfa"}:
            self.throttle_scope = "sensitive"
            throttles.append(ScopedRateThrottle())
        return throttles

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.select_for_update() if self.action in {"update", "partial_update", "role", "status"} else queryset

    def update(self, request, *args, **kwargs):
        # Commit password failures before returning validation errors.
        with transaction.atomic():
            instance = self.get_object()
            serializer = self.get_serializer(instance, data=request.data, partial=True)
            valid = serializer.is_valid()
            if valid:
                serializer.save()
        if not valid:
            raise serializers.ValidationError(serializer.errors)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="recover-mfa")
    @sensitive_variables()
    def recover_mfa(self, request, pk=None):
        target = self.get_object()
        if target == request.user or ((target.is_staff or target.is_superuser) and not request.user.is_superuser):
            raise serializers.ValidationError("Use a separate authorised operator for this recovery.")
        if request.data.get("identity_verified") is not True:
            raise serializers.ValidationError("Complete the documented identity verification before approving recovery.")
        password = serializers.CharField(max_length=256, trim_whitespace=False).run_validation(request.data.get("current_password"))
        sid = request.auth.get("sid") if request.auth else request.session.get("account_session")
        with transaction.atomic():
            actor = User.objects.select_for_update().get(pk=request.user.pk)
            recent = AccountSession.objects.filter(pk=sid, user=actor, revoked=False, mfa_verified=True,
                created_at__gte=timezone.now() - timedelta(minutes=5), expires_at__gt=timezone.now()).exists()
            accepted = recent and verify_sensitive_password(actor, password)
            if accepted:
                target = User.objects.select_for_update().get(pk=target.pk)
                target.mfa_secret = target.mfa_pending_secret = ""
                target.mfa_pending_at = None
                target.mfa_recovery_hashes = []
                target.mfa_last_step = -1
                target.challenge_nonce = uuid.uuid4()
                target.token_version += 1
                target.save()
                target.account_sessions.update(revoked=True)
                event("mfa_recovery_approved", actor, target=target)
        if not accepted:
            raise serializers.ValidationError("Sign in with MFA again and confirm your password before approving recovery.")
        return Response({"detail": "Authenticator reset. The user must sign in and enrol a new authenticator."})

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
