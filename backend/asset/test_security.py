import hashlib
import io
import json
import logging
import struct
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from django.core import signing
from django.core.cache import cache
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from user import test_security as accounts
from backend.middleware import RedactSignedMediaTokens
from .files import file_digest, validate_file
from .models import Asset


def image_bytes(kind="PNG"):
    output = io.BytesIO()
    Image.new("RGB", (3, 3), "red").save(output, format=kind)
    return output.getvalue()


def glb_bytes(document=None):
    binary = b""
    if document is None:
        binary = struct.pack("<9f3H", 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 2)
        document = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}],
            "nodes": [{"mesh": 0}], "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
            "buffers": [{"byteLength": len(binary)}],
            "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 36}, {"buffer": 0, "byteOffset": 36, "byteLength": 6}],
            "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3", "min": [0, 0, 0], "max": [1, 1, 0]},
                          {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"}]}
    body = json.dumps(document).encode()
    body += b" " * (-len(body) % 4)
    binary += bytes(-len(binary) % 4)
    tail = struct.pack("<I4s", len(binary), b"BIN\x00") + binary if binary else b""
    return struct.pack("<4sIII4s", b"glTF", 2, 20 + len(body) + len(tail), len(body), b"JSON") + body + tail


def mp4_structure():
    # Structural fixture; real MP4 streaming is also checked separately with MDN media.
    def box(kind, data):
        return struct.pack(">I4s", 8 + len(data), kind) + data
    tables = b"".join(box(key, bytes(size)) for key, size in
        ((b"stsd", 8), (b"stts", 8), (b"stsc", 8), (b"stsz", 12), (b"stco", 8)))
    reference = box(b"url ", b"\0\0\0\1")
    dinf = box(b"dinf", box(b"dref", struct.pack(">II", 0, 1) + reference))
    minf = box(b"minf", dinf + box(b"stbl", tables))
    handler = bytes(8) + b"vide" + bytes(12)
    mdia = box(b"mdia", box(b"mdhd", bytes(24)) + box(b"hdlr", handler) + minf)
    moov = box(b"moov", box(b"mvhd", bytes(100)) + box(b"trak", box(b"tkhd", bytes(84)) + mdia))
    return box(b"ftyp", b"isom" + bytes(4)) + moov + box(b"mdat", b"sample")


class AssetSecurityTests(TestCase):
    user = accounts.AccountSecurityTests.user
    login = accounts.AccountSecurityTests.login
    enrol = accounts.AccountSecurityTests.enrol
    sign_in = accounts.AccountSecurityTests.sign_in

    def setUp(self):
        cache.clear()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=temporary.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.root = Path(temporary.name)
        self.client = APIClient()
        self.editor = self.user("editor", role="Editor")
        self.sign_in(self.editor)

    def upload(self, content=None, filename="image.png", **values):
        return self.client.post("/assets/", {"name": "Example", "description": "Security fixture",
            "url": SimpleUploadedFile(filename, content if content is not None else image_bytes(), content_type="text/plain"),
            **values}, format="multipart")

    def path(self, data):
        return data["url"].split("http://testserver", 1)[-1]

    def read(self, response):
        try:
            return b"".join(response.streaming_content)
        finally:
            response.close()

    def test_upload_and_authenticated_previews_downloads_and_ranges(self):
        for name, content, mime in (("image.png", image_bytes(), "image/png"),
                ("image.jpg", image_bytes("JPEG"), "image/jpeg"),
                ("model.glb", glb_bytes(), "model/gltf-binary"),
                ("video.mp4", mp4_structure(), "video/mp4")):
            cache.clear()
            result = self.upload(content, name)
            self.assertEqual(result.status_code, 201, result.data)
            self.assertEqual(result.data["sha256"], hashlib.sha256(content).hexdigest())
            asset = Asset.objects.get(pk=result.data["id"])
            self.assertNotIn("image", asset.url.name)
            path = self.path(result.data)
            with self.assertLogs("dam.audit", level="INFO") as logs:
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], mime)
                self.assertEqual(self.read(response), content)
            self.assertNotIn("token=", " ".join(logs.output))
            response = self.client.head(path)
            self.assertEqual(response.status_code, 200)
            response.close()
            response = self.client.get(path, HTTP_RANGE="bytes=0-7")
            self.assertEqual(response.status_code, 206)
            self.assertEqual(self.read(response), content[:8])
            self.assertEqual(self.client.get(path, HTTP_RANGE=f"bytes={len(content)}-").status_code, 416)
            response = self.client.get(path + "&download=1")
            self.assertIn("attachment", response["Content-Disposition"])
            self.assertEqual(self.read(response), content)

    def test_anonymous_and_other_users_cannot_redeem_issued_urls(self):
        asset = self.upload().data
        path = self.path(asset)
        anonymous = APIClient()
        self.assertEqual(anonymous.get(f"/assets/{asset['id']}/media-url/").status_code, 401)
        for headers in ({}, {"HTTP_RANGE": "bytes=0-7"}):
            self.assertEqual(anonymous.get(path, **headers).status_code, 401)
        other = APIClient()
        self.sign_in(self.user("viewer"), other)
        self.assertEqual(other.get(path).status_code, 403)
        self.assertEqual(other.get(path, HTTP_RANGE="bytes=0-7").status_code, 403)
        own = other.get(f"/assets/{asset['id']}/media-url/")
        self.assertEqual(own.status_code, 200)
        self.assertEqual(self.read(other.get(self.path(own.data))), image_bytes())

    def test_tampered_expired_malformed_and_asset_substitution_links_fail(self):
        first, second = self.upload().data, self.upload().data
        path = self.path(first)
        self.assertEqual(self.client.get(path + "corrupt").status_code, 403)
        self.assertEqual(self.client.get(path.replace(first["id"], second["id"])).status_code, 403)
        self.assertEqual(self.client.get(path.split("?", 1)[0] + "?token=malformed").status_code, 403)
        # Only advance signed-link validation time, not JWT validation.
        original_loads = signing.loads
        def expired(*args, **kwargs):
            with patch("django.core.signing.time.time", return_value=time.time() + 301):
                return original_loads(*args, **kwargs)
        with patch("asset.media.signing.loads", side_effect=expired):
            self.assertEqual(self.client.get(path).status_code, 403)

    def test_revocation_and_deactivation_deny_access(self):
        path = self.path(self.upload().data)
        self.client.post("/api/logout/")
        self.assertEqual(self.client.get(path).status_code, 401)

    def test_original_session_revocation_denies_link_even_with_another_valid_login(self):
        path = self.path(self.upload().data)
        other_login = APIClient()
        self.sign_in(self.editor, other_login)
        self.assertEqual(self.read(other_login.get(path)), image_bytes())
        self.client.post("/api/logout/")
        self.assertEqual(other_login.get("/assets/").status_code, 200)
        self.assertEqual(other_login.get(path).status_code, 403)
        self.sign_in(self.editor)
        path = self.path(self.client.get("/assets/").data["results"][0])
        self.editor.refresh_from_db()
        self.editor.is_active = False
        self.editor.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(path).status_code, 401)

    def test_replacement_invalidates_old_link_but_historical_versions_still_work(self):
        first = self.upload().data
        old_path = self.path(first)
        second = self.upload(image_bytes("JPEG"), "new.jpg", code=first["code"])
        self.assertEqual(second.status_code, 201, second.data)
        versions = self.client.get(f"/get-all-file-versions/{first['code']}/")
        self.assertEqual(len(versions.data), 2)
        for version in versions.data:
            response = self.client.get(self.path(version))
            self.assertEqual(response.status_code, 200)
            response.close()
        result = self.client.patch(f"/assets/{first['id']}/", {"url": SimpleUploadedFile("replace.jpg", image_bytes("JPEG"))}, format="multipart")
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(self.client.get(old_path).status_code, 403)
        self.assertEqual(self.read(self.client.get(self.path(result.data))), image_bytes("JPEG"))
        self.assertNotEqual(first["sha256"], result.data["sha256"])

    def test_no_public_storage_routes_or_path_traversal(self):
        result = self.upload().data
        asset = Asset.objects.get(pk=result["id"])
        with self.assertRaises(ValueError):
            asset.url.storage.url(asset.url.name)
        for path in ("/media/" + asset.url.name, "/uploads/" + asset.url.name, "/media/../.env"):
            self.assertEqual(self.client.get(path).status_code, 404)
        for name in ("../.env", "uploads/../../.env", "C:/Windows/win.ini"):
            with self.assertRaises(SuspiciousFileOperation):
                asset.url.storage.path(name)
        Asset.objects.filter(pk=asset.pk).update(url="uploads/../../.env")
        self.assertEqual(self.client.get(f"/assets/{asset.pk}/media-url/").status_code, 404)

    def test_bad_extensions_truncation_external_resources_and_spoofing_are_rejected(self):
        for name, data in (("image.html", image_bytes()), ("fake.png", b"<script>bad</script>"),
                ("truncated.png", image_bytes()[:32]), ("truncated.jpg", image_bytes("JPEG")[:32]),
                ("model.glb", glb_bytes()[:-1]), ("video.mp4", mp4_structure()[:-3]),
                ("video.mp4", struct.pack(">I4s", 16, b"ftyp") + b"isom" + bytes(4)),
                ("model.glb", glb_bytes({"asset": {"version": "2.0"}, "buffers": [{"uri": "https://external.invalid/data", "byteLength": 1}]}))):
            cache.clear()
            response = self.upload(data, name)
            self.assertEqual(response.status_code, 400, (name, response.data))
        self.assertEqual(Asset.objects.count(), 0)

    @override_settings(ASSET_UPLOAD_MAX_BYTES=100)
    def test_upload_and_replacement_size_limits(self):
        good = self.upload()
        self.assertEqual(good.status_code, 201, good.data)
        self.assertEqual(self.upload(bytes(101)).status_code, 400)
        result = self.client.patch(f"/assets/{good.data['id']}/", {"url": SimpleUploadedFile("large.png", bytes(101))}, format="multipart")
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.read(self.client.get(self.path(good.data))), image_bytes())

    def test_integrity_verification_detects_tampering_without_rewriting_baseline(self):
        asset = Asset.objects.get(pk=self.upload().data["id"])
        call_command("verify_asset_files", stdout=io.StringIO())
        Path(asset.url.path).write_bytes(b"changed")
        with self.assertRaises(CommandError):
            call_command("verify_asset_files", stdout=io.StringIO(), stderr=io.StringIO())
        asset.refresh_from_db()
        self.assertEqual(asset.sha256, hashlib.sha256(image_bytes()).hexdigest())

    def test_repair_legacy_paths_by_digest_restores_previews_downloads_and_ranges(self):
        result = self.upload(glb_bytes(), "model.glb").data
        asset = Asset.objects.get(pk=result["id"])
        original = asset.url.name
        legacy = f"approved/{asset.pk.hex}/old-storage-key"
        Asset.objects.filter(pk=asset.pk).update(url=legacy)
        broken = self.client.get(f"/assets/{asset.pk}/").data
        self.assertEqual(self.client.get(self.path(broken)).status_code, 404)

        call_command("repair_asset_paths", stdout=io.StringIO())
        asset.refresh_from_db()
        self.assertEqual(asset.url.name, legacy)
        call_command("repair_asset_paths", apply=True, stdout=io.StringIO())
        asset.refresh_from_db()
        self.assertEqual(asset.url.name, original)
        self.assertEqual(asset.sha256, result["sha256"])
        self.assertEqual(asset.version_no, result["version_no"])
        self.assertEqual(self.client.get(self.path(broken)).status_code, 403)

        refreshed = self.client.get(f"/assets/{asset.pk}/media-url/")
        self.assertEqual(refreshed.status_code, 200)
        path = self.path(refreshed.data)
        self.assertEqual(self.read(self.client.get(path)), glb_bytes())
        self.assertEqual(self.read(self.client.get(path + "&download=1")), glb_bytes())
        response = self.client.get(path, HTTP_RANGE="bytes=0-7")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(self.read(response), glb_bytes()[:8])
        call_command("repair_asset_paths", apply=True, stdout=io.StringIO())
        call_command("verify_asset_files", stdout=io.StringIO())

    def test_repair_requires_a_matching_recorded_digest(self):
        for digest in ("", "0" * 64):
            with self.subTest(digest=digest):
                asset = Asset.objects.get(pk=self.upload().data["id"])
                legacy = f"approved/{asset.pk.hex}/missing"
                Asset.objects.filter(pk=asset.pk).update(url=legacy, sha256=digest)
                with self.assertRaises(CommandError):
                    call_command("repair_asset_paths", apply=True, stdout=io.StringIO(), stderr=io.StringIO())
                asset.refresh_from_db()
                self.assertEqual(asset.url.name, legacy)
                self.assertEqual(asset.sha256, digest)

    def test_repair_recovers_missing_upload_paths_and_preserves_accessible_files(self):
        first = Asset.objects.get(pk=self.upload().data["id"])
        second = Asset.objects.get(pk=self.upload().data["id"])
        first_path = first.url.name
        Asset.objects.filter(pk=second.pk).update(url="uploads/missing.png")
        call_command("repair_asset_paths", apply=True, stdout=io.StringIO())
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.url.name, first_path)
        self.assertTrue(second.url.storage.exists(second.url.name))
        call_command("verify_asset_files", stdout=io.StringIO())

    def test_repair_preserves_a_concurrent_file_replacement(self):
        asset = Asset.objects.get(pk=self.upload().data["id"])
        Asset.objects.filter(pk=asset.pk).update(url="uploads/missing.png")

        def replace_during_hash(file):
            Asset.objects.filter(pk=asset.pk).update(url="uploads/replacement.png", sha256="1" * 64)
            return file_digest(file)

        with patch("asset.management.commands.repair_asset_paths.file_digest", side_effect=replace_during_hash):
            with self.assertRaises(CommandError):
                call_command("repair_asset_paths", apply=True, stdout=io.StringIO(), stderr=io.StringIO())
        asset.refresh_from_db()
        self.assertEqual(asset.url.name, "uploads/replacement.png")
        self.assertEqual(asset.sha256, "1" * 64)

    def test_multiple_files_and_client_digest_are_rejected(self):
        result = self.client.post("/assets/", {"name": "Bad", "description": "Bad",
            "url": [SimpleUploadedFile("one.png", image_bytes()), SimpleUploadedFile("two.png", image_bytes())]}, format="multipart")
        self.assertEqual(result.status_code, 400)
        result = self.upload(sha256="0" * 64)
        self.assertEqual(result.status_code, 400)
        self.assertEqual(Asset.objects.count(), 0)

    def test_log_filter_redacts_signed_query_tokens(self):
        record = logging.LogRecord("django.server", logging.INFO, "", 0, '"GET %s HTTP/1.1"', ("/media/assets/id/?token=secret&download=1",), None)
        RedactSignedMediaTokens().filter(record)
        self.assertNotIn("secret", record.getMessage())
        self.assertIn("download=1", record.getMessage())
