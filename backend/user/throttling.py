import hashlib

from rest_framework.throttling import ScopedRateThrottle


class AccountRateThrottle(ScopedRateThrottle):
    """Additional hashed account key; DB lockouts protect login/MFA across workers."""

    def get_cache_key(self, request, view):
        if not isinstance(request.data, dict):
            return None
        identity = str(request.data.get("email") or request.data.get("username") or "").strip().lower()
        if not identity:
            return None
        digest = hashlib.sha256(identity.encode()).hexdigest()
        return self.cache_format % {"scope": self.scope + "-account", "ident": digest}
