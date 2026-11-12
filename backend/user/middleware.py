from django.contrib.auth import logout
from django.utils.deprecation import MiddlewareMixin
from rest_framework.exceptions import AuthenticationFailed

from .security import session_record, clear_auth_cookies
from .models import AccountSession


class AccountSessionMiddleware(MiddlewareMixin):
    """Django Admin and every session-authenticated route share the account gate."""

    def process_request(self, request):
        if request.user.is_authenticated:
            try:
                session_record(request.user, request.session.get("account_session"), True)
            except AuthenticationFailed:
                logout(request)
        if request.path_info == "/admin/logout/" and request.method == "POST" and request.user.is_authenticated:
            request.security_logout_session = request.session.get("account_session")

    def process_response(self, request, response):
        sid = getattr(request, "security_logout_session", None)
        if sid and response.status_code < 400:
            AccountSession.objects.filter(pk=sid).update(revoked=True)
            clear_auth_cookies(response)
        return response
