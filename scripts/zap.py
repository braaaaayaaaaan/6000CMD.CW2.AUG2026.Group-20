"""No-install launcher. Every destructive action is restricted to .zap/state."""
import argparse
import csv
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
from backend.zap_safety import (  # noqa: E402
    API, DIRECTORIES, FRONTEND, HOST, ROOT, STATE, check_state, clean_environment, safe_path, read_secrets,
)


def branch_check():
    result = subprocess.run(["git", "-C", str(REPO), "branch", "--show-current"],
                            check=True, capture_output=True, text=True)
    if result.stdout.strip() != "test/owasp-zap":
        raise RuntimeError("ZAP requires test/owasp-zap. No branch was switched.")


def private_file(path, content):
    path = safe_path(path)
    with path.open("x", encoding="utf-8") as file:
        file.write(content)
    path.chmod(0o600)


@contextmanager
def lifecycle_lock():
    safe_path(ROOT).mkdir(exist_ok=True)
    path = safe_path(ROOT / "run.lock")
    with path.open("a+b") as file:
        file.seek(0)
        if path.stat().st_size == 0:
            file.write(b"0")
            file.flush()
        file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError("ZAP is running or another command holds its lock. Stop it first.") from None
        try:
            yield
        finally:
            file.seek(0)
            if os.name == "nt":
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(file, fcntl.LOCK_UN)


def django_command(*args):
    subprocess.run([sys.executable, "-B", str(REPO / "backend/manage.py"), *args],
                   cwd=REPO / "backend", env=clean_environment(), check=True)


def certificates():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    directory = safe_path(ROOT / "certs")
    directory.mkdir(exist_ok=True)
    files = [directory / name for name in ("ca.crt", "server.crt", "server.key")]
    if all(safe_path(path).is_file() for path in files):
        cert = x509.load_pem_x509_certificate(files[1].read_bytes())
        if cert.not_valid_after_utc < datetime.now(timezone.utc) + timedelta(days=1):
            raise RuntimeError("ZAP TLS certificate expired. Remove only .zap/certs while stopped, then init.")
        return
    if any(path.exists() for path in files):
        raise RuntimeError("Incomplete ZAP certificates. Inspect .zap/certs before continuing.")
    now = datetime.now(timezone.utc)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Disposable DAM ZAP local CA")])
    ca = (x509.CertificateBuilder().subject_name(issuer).issuer_name(issuer)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=365))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), False)
          .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False)
          .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), True)
          .sign(ca_key, hashes.SHA256()))
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "DAM ZAP loopback")]))
            .issuer_name(issuer).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=180))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(HOST))]), False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False)
            .add_extension(x509.KeyUsage(True, False, True, False, False, False, False, False, False), True)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), False)
            .sign(ca_key, hashes.SHA256()))
    for path, content in ((files[0], ca.public_bytes(serialization.Encoding.PEM)),
                          (files[1], cert.public_bytes(serialization.Encoding.PEM)),
                          (files[2], key.private_bytes(serialization.Encoding.PEM,
                           serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))):
        private_file(path, content.decode("ascii"))
    # CA signing key deliberately never persisted.


def initialise():
    from cryptography.fernet import Fernet
    check_state()
    # chmod alone does not make secrets private on Windows NTFS.
    if os.name == "nt":
        identity = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], check=True,
                                  capture_output=True, text=True)
        sid = next(csv.reader([identity.stdout.strip()]))[1]
        subprocess.run(["icacls", str(ROOT), "/inheritance:r", "/grant:r",
                        f"*{sid}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        ROOT.chmod(0o700)
    STATE.mkdir(exist_ok=True)
    for name in DIRECTORIES:
        (STATE / name).mkdir(exist_ok=True)
    secrets_path = STATE / "secrets.json"
    if not secrets_path.exists():
        private_file(secrets_path, json.dumps({
            "django": secrets.token_urlsafe(64), "mfa": Fernet.generate_key().decode(),
            "environment": secrets.token_urlsafe(32),
        }))
    certificates()
    django_command("check")
    django_command("migrate", "--noinput", "--verbosity", "0")
    django_command("seed_zap")
    django_command("collectstatic", "--noinput", "--verbosity", "0")
    print("Initialised disposable SQLite state. Credentials: .zap/state/accounts.json (never logged).")


def stage_frontend():
    source = REPO / "frontend"
    if not (source / "node_modules/next/dist/bin/next").is_file():
        raise RuntimeError("Existing frontend/node_modules required; no dependencies are installed.")
    stage = safe_path(ROOT / "frontend")
    stage.mkdir(exist_ok=True)
    dedicated_env = (
        "DAM_ZAP_FRONTEND=1\nNEXT_PUBLIC_ZAP=1\nNEXT_PUBLIC_API_URL=" + API
        + "\nNEXT_PUBLIC_MODEL_VIEWER_URL=/zap-vendor/model-viewer.min.js\nNEXT_TELEMETRY_DISABLED=1\n"
    )
    for path in stage.glob(".env*"):
        safe_path(path)
        if path.name != ".env.local" or path.read_text(encoding="utf-8") != dedicated_env:
            raise RuntimeError("Unexpected environment file in the isolated frontend.")
    safe_path(stage / ".env.local").write_text(dedicated_env, encoding="utf-8")
    # Only allowlisted source files; .env*, .next and uploaded files are never copied.
    for name in ("src", "public"):
        target = safe_path(stage / name)
        if target.exists():
            for path in target.rglob("*"):
                safe_path(path)
            shutil.rmtree(target)
        for path in (source / name).rglob("*"):
            if path.is_symlink() or path.is_junction():
                raise RuntimeError("Refusing frontend source links during isolated staging.")
        if name == "public" and not (source / name).exists():
            target.mkdir()
        else:
            shutil.copytree(source / name, target)
    for name in ("package.json", "package-lock.json", "jsconfig.json", "next.config.mjs"):
        shutil.copyfile(source / name, safe_path(stage / name))
    # Optional user-provided existing copy; the launcher never downloads it.
    viewer = safe_path(ROOT / "vendor/model-viewer.min.js")
    if viewer.is_file():
        (stage / "public/zap-vendor").mkdir(exist_ok=True)
        shutil.copyfile(viewer, safe_path(stage / "public/zap-vendor/model-viewer.min.js"))
    modules = stage / "node_modules"
    expected = (source / "node_modules").resolve()
    if modules.exists():
        if modules.resolve() != expected:
            raise RuntimeError("Unexpected isolated node_modules link.")
    elif os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(expected), str(modules))
    else:
        modules.symlink_to(expected, target_is_directory=True)
    return stage


def context():
    return ssl.create_default_context(cafile=str(ROOT / "certs/ca.crt"))


def probe(url, timeout=10):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise RuntimeError("Refusing an unexpected readiness redirect.")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                        urllib.request.HTTPSHandler(context=context()))
    with opener.open(url, timeout=timeout) as response:
        return response.read(), response.headers


def stop_child(child):
    if child.poll() is not None:
        return
    if os.name == "nt":
        # Only the process tree launched by this still-running supervisor.
        subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        os.killpg(child.pid, signal.SIGTERM)
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=5)


def start():
    check_state()
    if not (STATE / "accounts.json").is_file() or not (STATE / "zap.sqlite3").is_file():
        raise RuntimeError("Run init first.")
    certificates()
    django_command("check")
    for port in (3443, 8443):
        with socket.socket() as listener:
            listener.bind((HOST, port))  # Refuse occupied ports; never reuse another app.
    stage = stage_frontend()
    safe_path(ROOT / "stop.request").unlink(missing_ok=True)
    environment = clean_environment()
    frontend_env = {**environment, "DAM_ZAP_FRONTEND": "1", "NEXT_PUBLIC_ZAP": "1",
                    "NEXT_PUBLIC_API_URL": API, "NEXT_PUBLIC_MODEL_VIEWER_URL": "/zap-vendor/model-viewer.min.js",
                    "NODE_ENV": "development"}
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Existing Node.js required.")
    commands = [
        ([sys.executable, "-B", str(Path(__file__).resolve()), "serve"], REPO, environment, "backend.log"),
        ([node, str(REPO / "frontend/node_modules/next/dist/bin/next"), "dev", str(stage),
          "--webpack", "--hostname", HOST, "--port", "3443", "--experimental-https",
          "--experimental-https-key", str(ROOT / "certs/server.key"),
          "--experimental-https-cert", str(ROOT / "certs/server.crt")], stage, frontend_env, "frontend.log"),
    ]
    children, logs = [], []
    try:
        for command, cwd, env, log_name in commands:
            log = safe_path(STATE / "logs" / log_name).open("ab")
            logs.append(log)
            children.append(subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=log,
                            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                            start_new_session=os.name != "nt"))
        marker = safe_path(ROOT / "running.json")
        marker.write_text(json.dumps({"supervisor": os.getpid(), "children": [c.pid for c in children]}), encoding="utf-8")
        # Actual page compilation can take a minute on a cold webpack cache.
        deadline = time.monotonic() + 180
        ready = False
        while time.monotonic() < deadline:
            if any(child.poll() is not None for child in children):
                raise RuntimeError("A ZAP process exited; see .zap/state/logs (private).")
            if (ROOT / "stop.request").exists():
                return
            try:
                _, api_headers = probe(API + "/api/account/csrf/", timeout=3)
                _, frontend_headers = probe(FRONTEND + "/login", timeout=8)
                expected = hashlib.sha256(read_secrets()["environment"].encode()).hexdigest()
                if (api_headers.get("X-DAM-ZAP-Instance") != expected
                        or frontend_headers.get("X-DAM-Environment") != "disposable-zap"):
                    raise RuntimeError("Listeners are not serving the expected isolated environment.")
                ready = True
                break
            except (OSError, urllib.error.URLError):
                time.sleep(1)
        if not ready:
            raise RuntimeError("ZAP readiness timed out; see .zap/state/logs.")
        print(f"ZAP frontend: {FRONTEND}\nZAP backend:  {API}\nReady. Ctrl+C or scripts/zap.ps1 stop shuts down only these processes.", flush=True)
        while not (ROOT / "stop.request").exists():
            if any(child.poll() is not None for child in children):
                raise RuntimeError("A ZAP process exited; stopping its sibling.")
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for child in reversed(children):
            stop_child(child)
        for log in logs:
            log.close()
        safe_path(ROOT / "running.json").unlink(missing_ok=True)
        safe_path(ROOT / "stop.request").unlink(missing_ok=True)
        print("ZAP processes stopped.", flush=True)


def serve():
    """TLS-wrapped Django WSGI, retaining real middleware, permissions and logging."""
    import django
    from django.conf import settings
    from django.core.handlers.wsgi import WSGIHandler
    from django.db import close_old_connections, connections
    from django.contrib.staticfiles.handlers import StaticFilesHandler
    from socketserver import ThreadingMixIn
    from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server
    from backend.zap_safety import assert_isolated

    django.setup()
    assert_isolated(settings)

    def outbound_guard(event, args):
        if event in {"socket.connect", "socket.getaddrinfo"}:
            raise PermissionError("Outbound networking is disabled in the ZAP backend.")
    sys.addaudithook(outbound_guard)

    class Server(ThreadingMixIn, WSGIServer):
        daemon_threads = True

    class Handler(WSGIRequestHandler):
        def get_environ(self):
            environ = super().get_environ()
            environ["HTTPS"] = "on"
            environ["wsgi.url_scheme"] = "https"
            return environ

        def address_string(self):
            return self.client_address[0]

        def log_message(self, fmt, *args):
            # Application audit/monitoring remains enabled. Avoid raw request URLs.
            pass

    app = StaticFilesHandler(WSGIHandler())

    def application(environ, start_response):
        close_old_connections()
        result = None
        def isolated_response(status, headers, exc_info=None):
            headers.extend([("X-DAM-Environment", "disposable-zap"),
                            ("X-DAM-ZAP-Instance", settings.ZAP_ENVIRONMENT_ID)])
            return start_response(status, headers, exc_info)
        try:
            result = app(environ, isolated_response)
            yield from result
        finally:
            if result is not None and hasattr(result, "close"):
                result.close()
            connections.close_all()

    server = make_server(HOST, 8443, application, server_class=Server, handler_class=Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(str(ROOT / "certs/server.crt"), str(ROOT / "certs/server.key"))
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    print("Isolated SQLite HTTPS backend ready.", flush=True)
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("init", "reset", "start", "stop", "status", "verify", "serve"))
    action = parser.parse_args().action
    branch_check()
    check_state()
    if action == "serve":
        serve()
    elif action == "stop":
        if not safe_path(ROOT / "running.json").exists():
            print("No supervised ZAP environment is running.")
            return
        safe_path(ROOT / "stop.request").write_text("stop", encoding="ascii")
        deadline = time.monotonic() + 25
        while (ROOT / "running.json").exists() and time.monotonic() < deadline:
            time.sleep(0.25)
        if (ROOT / "running.json").exists():
            raise RuntimeError("Stop was not acknowledged. Inspect the original startup terminal; no unknown processes were killed.")
        print("The supervised ZAP processes have stopped.")
    elif action == "verify":
        if not (ROOT / "running.json").is_file():
            raise RuntimeError("Start ZAP in another terminal before verify.")
        django_command("verify_zap")
    elif action == "status":
        print("Supervised process marker: " + ("present" if (ROOT / "running.json").exists() else "absent"))
        print("SQLite state: " + ("present" if (STATE / "zap.sqlite3").exists() else "absent"))
        if (ROOT / "running.json").exists():
            _, headers = probe(API + "/api/account/csrf/")
            expected = hashlib.sha256(read_secrets()["environment"].encode()).hexdigest()
            if headers.get("X-DAM-ZAP-Instance") != expected:
                raise RuntimeError("Listener does not match the current isolated state.")
            print("HTTPS backend responds with a certificate verified against the dedicated CA.")
        print(f"Frontend {FRONTEND}\nBackend {API}")
    else:
        with lifecycle_lock():
            if action == "reset":
                # check_state rejects links first; only this fixed subtree is removed.
                if STATE.exists():
                    shutil.rmtree(safe_path(STATE))
                initialise()
                print("Reset only .zap/state; accounts, keys, uploads, email and audit records regenerated.")
            elif action == "init":
                initialise()
            else:
                start()


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        # Never dump credential-bearing locals, URLs or exception details.
        print(f"ZAP command failed ({type(error).__name__}). Check setup, branch and private logs.", file=sys.stderr)
        if isinstance(error, RuntimeError):
            print(str(error), file=sys.stderr)
        if isinstance(error, urllib.error.URLError):
            print("Loopback HTTPS readiness failed. Check the generated CA/certificate and local listener.", file=sys.stderr)
        sys.exit(1)
