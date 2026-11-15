"""Targeted live workflow verification, not a vulnerability scanner."""
import hashlib
import http.cookiejar
import io
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import pyotp
from PIL import Image
from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from backend.zap_safety import API, DATABASE, FRONTEND, ROOT, STATE, assert_isolated, safe_path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CommandError("Verification refused an HTTP redirect.")


class Browser:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(ROOT / "certs/ca.crt"))),
            urllib.request.HTTPCookieProcessor(self.jar),
        )
        self.csrf = ""

    def request(self, method, path, data=None, *, body=None, content_type=None, csrf=True):
        url = urllib.parse.urljoin(API + "/", path)
        if (urllib.parse.urlsplit(url).scheme != "https"
                or urllib.parse.urlsplit(url).netloc != urllib.parse.urlsplit(API).netloc):
            raise CommandError("Verification refused a URL outside the isolated API.")
        headers = {"Origin": FRONTEND, "Referer": FRONTEND + "/login"}
        if method not in {"GET", "HEAD", "OPTIONS"} and csrf:
            headers["X-CSRFToken"] = self.csrf
        if data is not None:
            body = json.dumps(data).encode()
            content_type = "application/json"
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            response = self.opener.open(request, timeout=40)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw, status, response_headers = response.read(), response.status, response.headers
        if "application/json" in response_headers.get("Content-Type", ""):
            result = json.loads(raw)
            if isinstance(result, dict) and result.get("csrfToken"):
                self.csrf = result["csrfToken"]
        else:
            result = raw
        return status, result, response_headers

    def bootstrap(self):
        status, data, _ = self.request("GET", "/api/account/csrf/")
        if status != 200 or not data.get("csrfToken"):
            raise CommandError("Isolated CSRF endpoint did not respond correctly.")

    def upload(self, name, payload, filename="check.png"):
        boundary = "zapcheck" + uuid.uuid4().hex
        body = b""
        for key, value in (("name", name), ("description", "Disposable live verification")):
            body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n').encode()
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="url"; filename="{filename}"\r\n'
                 'Content-Type: image/png\r\n\r\n').encode() + payload + f"\r\n--{boundary}--\r\n".encode()
        return self.request("POST", "/assets/", body=body, content_type=f"multipart/form-data; boundary={boundary}")


class Command(BaseCommand):
    help = "Verify real HTTPS authentication and asset workflows only against the disposable ZAP instance."

    def handle(self, *args, **options):
        if not getattr(settings, "ZAP_ISOLATED", False):
            raise CommandError("verify_zap requires the dedicated ZAP launcher.")
        assert_isolated(settings)
        from user.models import AuditEvent, User
        from user.security import reserve_email
        from asset.models import Asset
        checks = []

        def require(condition, description):
            if not condition:
                raise CommandError("Live verification failed: " + description)
            checks.append(description)

        with connection.cursor() as cursor:
            cursor.execute("PRAGMA database_list")
            databases = cursor.fetchall()
        require(connection.vendor == "sqlite" and any(row[1] == "main" and row[2] == str(DATABASE) for row in databases),
                "SQLite connection uses only .zap/state/zap.sqlite3")
        proof = Browser().request("GET", "/api/account/csrf/")
        require(proof[2].get("X-DAM-ZAP-Instance") == settings.ZAP_ENVIRONMENT_ID,
                "Live HTTPS server proves the current isolated configuration identity")
        suffix = uuid.uuid4().hex[:12]
        users = []
        uploaded_ids = []
        clients = {}
        password = uuid.uuid4().hex + "!aA9"
        try:
            # Dedicated synthetic users; no credentials or MFA seeds are printed or saved.
            for role in ("Viewer", "Editor", "Admin"):
                user = User.objects.create_user(username=f"check_{role.lower()}_{suffix}",
                    email=f"check_{role.lower()}_{suffix}@example.invalid", password=password,
                    email_verified=True, is_staff=role == "Admin")
                user.groups.add(Group.objects.get(name=role))
                reserve_email(user)
                users.append(user)
                client = Browser()
                client.bootstrap()
                require(client.request("POST", "/api/token/", {"username": user.username, "password": password}, csrf=False)[0] == 403,
                        role + ": CSRF required for login")
                first = client.request("POST", "/api/token/", {"username": user.username, "password": password})
                require(first[0] == 200 and first[1].get("enrolment_required") and first[1].get("mfa_required"),
                        role + ": password alone requires MFA enrolment")
                require(client.request("GET", "/assets/")[0] == 401,
                        role + ": password challenge grants no asset access")
                challenge = first[1]["challenge"]
                setup = client.request("POST", "/api/account/mfa/enrol/", {"challenge": challenge})
                require(setup[0] == 200 and "secret" in setup[1], role + ": normal MFA enrolment works")
                code = pyotp.TOTP(setup[1]["secret"]).now()
                confirmed = client.request("POST", "/api/account/mfa/confirm/", {"challenge": challenge, "code": code})
                require(confirmed[0] == 200 and confirmed[1].get("user", {}).get("group") == role,
                        role + ": real TOTP creates correct role session")
                cookies = list(client.jar)
                require(any(c.name == "zap_access" and c.secure and c.has_nonstandard_attr("HttpOnly") for c in cookies)
                        and not any(c.name in {"dam_access", "dam_refresh", "sessionid", "csrftoken"} for c in cookies),
                        role + ": isolated Secure/HttpOnly authentication cookies")
                require(client.request("POST", "/api/token/refresh/", {})[0] == 200,
                        role + ": refresh rotation succeeds")
                require(client.request("GET", "/api/account/me/")[0] == 200,
                        role + ": authenticated profile succeeds")
                clients[role] = client
            viewer, editor, admin = (clients[role] for role in ("Viewer", "Editor", "Admin"))
            require(viewer.request("GET", "/assets/")[0] == 200, "Viewer can list published assets")
            output = io.BytesIO()
            Image.new("RGB", (8, 8), "green").save(output, "PNG")
            payload = output.getvalue()
            require(viewer.upload("Denied " + suffix, payload)[0] == 403, "Viewer cannot upload")
            require(editor.upload("Malformed " + suffix, b"not an image")[0] == 400, "Malformed uploads rejected")
            result = editor.upload("Live " + suffix, payload)
            require(result[0] == 201, "Editor can upload through the real multipart parser")
            asset_id = result[1]["id"]
            uploaded_ids.append(asset_id)
            require(result[1]["sha256"] == hashlib.sha256(payload).hexdigest(), "Upload records real SHA-256 digest")
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                detail = editor.request("GET", f"/assets/{asset_id}/")
                if detail[0] == 200 and detail[1]["processing_status"] == "approved":
                    break
                time.sleep(0.25)
            require(detail[0] == 200 and detail[1]["processing_status"] == "approved",
                    "Image decoder subprocess approves and promotes quarantined upload")
            asset = Asset.objects.get(pk=asset_id)
            require(asset.url.storage.location == str(STATE / "private_assets")
                    and safe_path(asset.url.path).is_file(), "Approved file uses only isolated private storage")
            require(viewer.request("PATCH", f"/assets/{asset_id}/", {"description": "denied"})[0] == 403,
                    "Viewer cannot edit asset metadata")
            require(editor.request("PATCH", f"/assets/{asset_id}/", {"description": "Verified metadata"})[0] == 200,
                    "Editor can edit asset metadata")
            signed = viewer.request("GET", f"/assets/{asset_id}/media-url/")
            require(signed[0] == 200 and bool(signed[1].get("url")), "Viewer obtains an authorised signed URL")
            url = signed[1]["url"]
            downloaded = viewer.request("GET", url)
            require(downloaded[0] == 200 and hashlib.sha256(downloaded[1]).hexdigest() == asset.sha256,
                    "Signed download streams the original bytes with matching SHA-256")
            anonymous = Browser()
            require(anonymous.request("GET", url)[0] in {401, 403}, "Anonymous client cannot reuse signed media URL")
            require(editor.request("GET", url)[0] in {401, 403}, "Signed media URL is bound to the issuing user/session")
            require(viewer.request("GET", url + "x")[0] in {400, 403, 404}, "Tampered media signature rejected")
            require(viewer.request("GET", "/media/" + asset.url.name)[0] == 404, "Private storage has no public route")
            require(viewer.request("GET", "/api/security/overview/")[0] == 403,
                    "Viewer cannot access security monitoring")
            require(admin.request("GET", "/api/security/overview/")[0] == 200,
                    "Admin can access security monitoring")
            require(AuditEvent.objects.filter(actor__in=users, event_type="login_succeeded").count() >= 3,
                    "Security audit records persist in isolated SQLite")
            # Exercise ordinary signup, captured verification email and link validation.
            signup = Browser()
            signup.bootstrap()
            username = "check_signup_" + suffix
            email = username + "@example.invalid"
            before = set((STATE / "email").glob("*"))
            created = signup.request("POST", "/users/", {"username": username, "email": email,
                "password1": password, "password2": password, "first_name": "Synthetic", "last_name": "Check"})
            require(created[0] == 201, "Normal signup works without external email delivery")
            registered = User.objects.get(username=username)
            users.append(registered)
            require(not registered.email_verified, "New signup still requires email verification")
            captured = [path for path in (STATE / "email").glob("*") if path not in before]
            require(bool(captured), "Verification email captured only inside .zap/state/email")
            message = "\n".join(path.read_text(encoding="utf-8") for path in captured)
            import re
            links = re.findall(re.escape(FRONTEND) + r"/verify-email#[^\s]+", message)
            require(bool(links), "Captured verification link targets only the isolated frontend")
            values = {key: value[0] for key, value in urllib.parse.parse_qs(urllib.parse.urlsplit(links[-1]).fragment).items()}
            require(signup.request("POST", "/api/account/verify-email/", {"token": values["token"]})[0] == 200,
                    "Normal verification token is accepted")
            before = {path: path.stat().st_size for path in (STATE / "email").glob("*")}
            require(editor.request("POST", "/api/account/forgot-password/", {"email": users[1].email})[0] == 200,
                    "Password recovery endpoint succeeds")
            require(any(path not in before or path.stat().st_size > before[path] for path in (STATE / "email").glob("*")),
                    "Recovery email is captured locally")
            require(viewer.request("POST", "/api/logout/", {})[0] in {200, 204}, "Normal logout succeeds")
            require(viewer.request("GET", url)[0] in {401, 403}, "Logout revokes signed media access")
            require(viewer.request("GET", "/api/account/me/")[0] == 401, "Logged-out session cannot access profile")
            require(admin.request("DELETE", f"/assets/{asset_id}/")[0] == 204, "Admin can delete disposable asset")
            uploaded_ids.remove(asset_id)
            require(not safe_path(asset.url.path).exists(), "Asset deletion removes only its isolated file")
            # Check real Next rendering over HTTPS, without any development server reuse.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(ROOT / "certs/ca.crt"))))
            for route in ("/login", "/signup", "/forgot-password", "/editor/home", "/editor/uploads", "/editor/security"):
                with opener.open(FRONTEND + route, timeout=60) as response:
                    html = response.read()
                    require(response.status == 200 and b"<html" in html
                            and response.headers.get("X-DAM-Environment") == "disposable-zap",
                            "Next.js renders " + route + " from the isolated frontend")
            report = {"result": "PASS", "checks": checks, "database": ".zap/state/zap.sqlite3",
                      "frontend": FRONTEND, "backend": API,
                      "limitations": ["SQLite does not emulate PostgreSQL row locks, SQL dialect or privileges.",
                                      "Browser interaction and ZAP scans are not performed by this verifier."]}
            safe_path(STATE / "verification-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            self.stdout.write(f"PASS: {len(checks)} live HTTPS/configuration checks. Report: .zap/state/verification-report.json")
        finally:
            # These rows were created above with unguessable identifiers; fixtures are retained.
            Asset.objects.filter(pk__in=uploaded_ids).delete()
            User.objects.filter(pk__in=[user.pk for user in users]).delete()
