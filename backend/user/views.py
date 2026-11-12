from django.contrib.auth import logout
from django.contrib.auth.models import Group
from django.contrib import admin
from django.db import transaction
from django.db.models import F
from django.http import HttpResponse
from django.views.decorators.cache import never_cache
from types import SimpleNamespace
import math
from rest_framework import permissions, viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .authentication import RevocableTokenRefreshSerializer
from .models import User
from .serializers import UserSerializer, GroupSerializer, NewTokenObtainPairSerializer


class IsAdminOrSelf(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        return request.user.is_staff or request.user.is_superuser or obj == request.user


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.order_by("-date_joined", "id").prefetch_related("groups")
    serializer_class = UserSerializer

    def get_permissions(self):
        if self.action == "create":
            return [permissions.AllowAny()]
        if self.action == "list":
            return [permissions.IsAdminUser()]
        return [IsAdminOrSelf()]

    def get_throttles(self):
        throttles = super().get_throttles()
        if self.action == "create":
            self.throttle_scope = "signup"
            throttles.append(ScopedRateThrottle())
        return throttles

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.select_for_update() if self.action in {"update", "partial_update"} else queryset

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return super().update(request, *args, **kwargs)


class GroupViewSet(viewsets.ModelViewSet):
    queryset = Group.objects.order_by("name", "id")
    serializer_class = GroupSerializer
    permission_classes = [permissions.IsAdminUser]


class NewTokenObtainPairView(TokenObtainPairView):
    serializer_class = NewTokenObtainPairSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


class NewTokenRefreshView(TokenRefreshView):
    serializer_class = RevocableTokenRefreshSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "refresh"


@api_view(["POST"])
def end_session(request):
    request._request.audit_actor = str(request.user.pk)
    User.objects.filter(pk=request.user.pk).update(token_version=F("token_version") + 1)
    logout(request._request)
    return Response(status=204)


@never_cache
def admin_login(request, extra_context=None):
    if request.method == "POST":
        throttle = ScopedRateThrottle()
        if not throttle.allow_request(request, SimpleNamespace(throttle_scope="login")):
            return HttpResponse("Too many login attempts. Please try again later.", status=429,
                                headers={"Retry-After": str(math.ceil(throttle.wait()))})
    return admin.site.login(request, extra_context=extra_context)
