"""Allow the configured frontend origins to frame local media previews."""

from django.conf import settings
from django.utils.deprecation import MiddlewareMixin


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
