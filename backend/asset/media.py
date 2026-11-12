import re
import time
import hashlib
import logging
import struct

from django.conf import settings
from django.core import signing
from django.core.exceptions import SuspiciousFileOperation, ValidationError as DjangoValidationError
from django.http import FileResponse, Http404, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.crypto import constant_time_compare
from django.utils.http import content_disposition_header
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from user.models import User
from user.security import session_record
from rest_framework.exceptions import AuthenticationFailed
from .files import MIME_TYPES, detect_type, validate_glb_container, validate_mp4
from .models import Asset

SALT = "asset-media"
MISSING_FILE_MESSAGE = "The original file is missing from server storage. Restore the upload or upload a replacement."


def file_binding(asset):
    return hashlib.sha256((asset.url.name + ":" + asset.sha256).encode()).hexdigest()


def signed_media_url(asset, request):
    user = getattr(request, "user", None)
    if not asset.is_published or not user or not user.is_authenticated:
        return {"url": None, "url_expires_at": None}
    sid = request.auth.get("sid") if getattr(request, "auth", None) else request.session.get("account_session")
    session_record(user, sid, True)
    token = signing.dumps({
        "asset": str(asset.pk), "user": str(user.pk), "version": user.token_version,
        "auth": user.get_session_auth_hash(),
        "file": file_binding(asset),
        "sid": str(request.auth.get("sid")) if getattr(request, "auth", None) else request.session.get("account_session"),
    }, salt=SALT, compress=True)
    path = reverse("asset-file", args=[asset.pk]) + "?token=" + token
    return {
        "url": request.build_absolute_uri(path),
        "url_expires_at": int(time.time()) + settings.MEDIA_URL_LIFETIME_SECONDS,
    }


@api_view(["GET", "HEAD"])
@permission_classes([IsAuthenticated])
@throttle_classes([])
def asset_file(request, asset_id):
    try:
        payload = signing.loads(
            request.query_params.get("token", ""),
            salt=SALT,
            max_age=settings.MEDIA_URL_LIFETIME_SECONDS,
        )
        user = User.objects.get(pk=payload["user"], is_active=True)
        if (payload["asset"] != str(asset_id) or payload["version"] != user.token_version
                or request.user.pk != user.pk
                or not constant_time_compare(payload["auth"], user.get_session_auth_hash())):
            raise PermissionDenied("This media link is no longer valid.")
        session_record(user, payload.get("sid"), True)
    except (signing.BadSignature, User.DoesNotExist, KeyError, ValueError, TypeError, AuthenticationFailed, DjangoValidationError):
        raise PermissionDenied("This media link is invalid or expired.") from None
    asset = get_object_or_404(Asset.published(), pk=asset_id)
    if payload.get("file") != file_binding(asset):
        raise PermissionDenied("This media link is no longer valid. Request a new link.")
    file = None
    try:
        file = asset.url.open("rb")
        kind = detect_type(file)
        size = asset.url.size
        # Legacy container uploads must not fetch external resources either.
        if kind in {"glb", "mp4"}:
            (validate_glb_container if kind == "glb" else validate_mp4)(file, size)
            file.seek(0)
    except (OSError, ValueError, SuspiciousFileOperation, TypeError, KeyError, AttributeError, struct.error, RecursionError):
        if file is not None:
            file.close()
        raise Http404(MISSING_FILE_MESSAGE) from None
    content_type = MIME_TYPES.get(kind, "application/octet-stream")
    filename = re.sub(r"[\x00-\x1f\x7f/\\]", "_", asset.name) + "." + (kind or "bin")
    attachment = kind is None or request.query_params.get("download") == "1"
    range_header = request.headers.get("Range")
    if range_header:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
        try:
            if not match or not any(match.groups()):
                raise ValueError()
            first, last = match.groups()
            start = int(first) if first else max(0, size - int(last))
            end = min(int(last), size - 1) if first and last else size - 1
            if start < 0 or start >= size or end < start:
                raise ValueError()
        except ValueError:
            file.close()
            response = StreamingHttpResponse(status=416)
            response["Content-Range"] = "bytes */" + str(size)
            return response
        file.seek(start)

        def chunks():
            remaining = end - start + 1
            try:
                while remaining:
                    block = file.read(min(65536, remaining))
                    if not block:
                        break
                    remaining -= len(block)
                    yield block
            finally:
                file.close()

        response = FileResponse(
            file, as_attachment=attachment, filename=filename, content_type=content_type
        )
        response.streaming_content = chunks()
        response.status_code = 206
        response["Content-Length"] = str(end - start + 1)
        response["Content-Range"] = "bytes %s-%s/%s" % (start, end, size)
        response["Content-Disposition"] = content_disposition_header(
            attachment, filename
        )
    else:
        response = FileResponse(
            file, as_attachment=attachment, filename=filename, content_type=content_type
        )
    response["Accept-Ranges"] = "bytes"
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response["Referrer-Policy"] = "no-referrer"
    logging.getLogger("dam.audit").info("event=asset_file_access actor=%s asset=%s status=%s", user.pk, asset.pk, response.status_code)
    return response
