"""Allow the configured frontend origins to frame local media previews."""

import logging
import re

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
    def process_request(self, request):
        from user.auditing import current_request
        request.audit_context_token = current_request.set(request)

    def process_response(self, request, response):
        from user.auditing import current_request, record_event
        try:
            if request.path_info.startswith("/admin/") and response.status_code == 403 and request.user.is_authenticated:
                record_event("access_denied", request.user, request=request, resource_id="django_admin",
                             metadata={"method": request.method})
        finally:
            token = getattr(request, "audit_context_token", None)
            if token is not None:
                current_request.reset(token)
        return response


class MediaFramePolicyMiddleware(MiddlewareMixin):
    def process_response(self, request, response):
        if not request.path_info.startswith(settings.MEDIA_URL):
            return response
        response["Cache-Control"] = "private, no-store"
        response["Referrer-Policy"] = "no-referrer"

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


class RedactSignedMediaTokens(logging.Filter):
    def filter(self, record):
        record.msg = re.sub(r"([?&]token=)[^&\s\"']+", r"\1[redacted]", record.getMessage())
        record.args = ()
        return True
