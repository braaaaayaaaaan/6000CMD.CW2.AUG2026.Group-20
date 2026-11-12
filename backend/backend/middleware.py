"""Allow the configured frontend origins to frame local media previews."""

import logging

from django.conf import settings
from django.utils.deprecation import MiddlewareMixin
from django.http import HttpResponse
from rest_framework.throttling import ScopedRateThrottle
from types import SimpleNamespace
import math


class LoginThrottleMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.method == "POST" and request.resolver_match.view_name == "rest_framework:login":
            throttle = ScopedRateThrottle()
            if not throttle.allow_request(request, SimpleNamespace(throttle_scope="login")):
                return HttpResponse("Too many login attempts. Please try again later.", status=429,
                                    headers={"Retry-After": str(math.ceil(throttle.wait()))})


class AuditMiddleware(MiddlewareMixin):
    def process_response(self, request, response):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            user = getattr(request, "user", None)
            actor = getattr(request, "audit_actor", None) or (str(user.pk) if user and user.is_authenticated else "anonymous")
            logging.getLogger("dam.audit").info(
                "actor=%s method=%s path=%r status=%s", actor,
                request.method, request.path_info, response.status_code,
            )
        return response


class MediaFramePolicyMiddleware(MiddlewareMixin):
    def process_response(self, request, response):
        if not request.path_info.startswith(settings.MEDIA_URL):
            return response

        origins = settings.MEDIA_FRAME_ALLOWED_ORIGINS
        ancestors = " ".join(["'self'", *origins])
        policy = response.get("Content-Security-Policy", "")
        # Preserve an existing frame-ancestors policy supplied by a view.
        if not any(
            part.strip().split()[:1] == ["frame-ancestors"]
            for part in policy.split(";")
        ):
            directive = f"frame-ancestors {ancestors}"
            response["Content-Security-Policy"] = (
                f"{policy.rstrip('; ')}; {directive}" if policy else directive
            )
        if origins:
            # CSP supports an origin allowlist; X-Frame-Options does not.
            response.headers.pop("X-Frame-Options", None)
        return response
