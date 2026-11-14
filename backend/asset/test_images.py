"""Image policy and real child-process validation with disposable storage only."""

import hashlib
import io
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from user import test_security as accounts
from .files import (
    JPEG_HEADER_MAX_MARKERS,
    process_uploads,
    run_validation_process,
    validate_file,
    validate_image,
)
from .models import Asset
from .test_security import image_bytes


def png_chunk(kind, data):
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data))
    )


def change_png_chunk(content, target, change):
    result, offset = content[:8], 8
    while offset < len(content):
        length = struct.unpack(">I", content[offset : offset + 4])[0]
        kind = content[offset + 4 : offset + 8]
        data = content[offset + 8 : offset + 8 + length]
        result += png_chunk(kind, change(data) if kind == target else data)
        offset += length + 12
    return result


def corrupt_png():
    # Correct IHDR and chunk CRCs, but an invalid compressed pixel stream.
    return change_png_chunk(image_bytes(), b"IDAT", lambda data: bytes(len(data)))


class ImageUploadTests(TestCase):
    user = accounts.AccountSecurityTests.user
    login = accounts.AccountSecurityTests.login
    enrol = accounts.AccountSecurityTests.enrol
    sign_in = accounts.AccountSecurityTests.sign_in

    def setUp(self):
        cache.clear()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        storage = override_settings(
            MEDIA_ROOT=str(Path(temporary.name) / "legacy"),
            ASSET_PRIVATE_ROOT=str(Path(temporary.name) / "private"),
        )
        storage.enable()
        self.addCleanup(storage.disable)
        self.client = APIClient()
        self.sign_in(self.user("image-editor", role="Editor"))

    def upload(self, content=None, filename="image.png", method="post", asset=None):
        path = "/assets/" if asset is None else f"/assets/{asset.pk}/"
        return getattr(self.client, method)(
            path,
            {
                "name": "Image",
                "description": "Isolated image fixture",
                "url": SimpleUploadedFile(
                    filename,
                    image_bytes() if content is None else content,
                    content_type="text/plain",
                ),
            },
            format="multipart",
        )

    def process(self, response, expected="approved"):
        self.assertIn(response.status_code, {200, 201}, response.data)
        asset = Asset.objects.get(pk=response.data["id"])
        self.assertEqual(asset.processing_status, "pending")
        self.assertFalse(asset.is_published)
        self.assertIsNone(response.data["url"])
        self.assertUnavailable(asset)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(process_uploads(asset_id=asset.pk), 1)
        asset.refresh_from_db()
        self.assertEqual(asset.processing_status, expected, asset.processing_detail)
        if expected != "approved":
            self.assertFalse(asset.is_published)
            self.assertTrue(asset.url.storage.exists(asset.url.name))
            self.assertUnavailable(asset)
        return asset

    def assertUnavailable(self, asset):
        self.assertEqual(
            self.client.get(f"/assets/{asset.pk}/media-url/").status_code, 404
        )
        for method in (self.client.get, self.client.head):
            for suffix in ("", "&download=1"):
                response = method(
                    f"/media/assets/{asset.pk}/?token=invalid{suffix}",
                    HTTP_RANGE="bytes=0-7",
                )
                self.assertEqual(response.status_code, 403)

    def download(self, asset):
        data = self.client.get(f"/assets/{asset.pk}/media-url/").data
        response = self.client.get(
            data["url"].replace("http://testserver", "") + "&download=1"
        )
        self.assertEqual(response.status_code, 200)
        try:
            return response, b"".join(response.streaming_content)
        finally:
            response.close()

    def test_jpeg_extensions_use_real_worker_and_preserve_bytes_and_mime(self):
        content = image_bytes("JPEG")
        for suffix in ("jpg", "jpeg", "JPG", "JPEG"):
            with self.subTest(suffix=suffix):
                asset = self.process(self.upload(content, f"photo.{suffix}"))
                self.assertEqual(asset.file_type, "jpg")
                self.assertRegex(
                    asset.url.name, r"^approved/[0-9a-f]{32}/[0-9a-f]{32}$"
                )
                response, downloaded = self.download(asset)
                self.assertEqual(response["Content-Type"], "image/jpeg")
                self.assertEqual(downloaded, content)
                self.assertEqual(hashlib.sha256(downloaded).hexdigest(), asset.sha256)

    def test_jpeg_mismatches_and_fake_files_are_rejected_on_all_upload_paths(self):
        original = self.process(self.upload())
        for method, asset in (("post", None), ("put", original), ("patch", original)):
            for content in (image_bytes(), b"plain text"):
                with self.subTest(method=method, content=content[:8]):
                    response = self.upload(content, "fake.jpeg", method, asset)
                    self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(Asset.objects.count(), 1)

    def test_jpeg_replacements_share_policy_and_keep_original(self):
        original = self.process(self.upload())
        for method, suffix in (("put", "jpeg"), ("patch", "JPEG")):
            replacement = self.process(
                self.upload(image_bytes("JPEG"), f"new.{suffix}", method, original)
            )
            self.assertNotEqual(original.pk, replacement.pk)
            self.assertGreater(replacement.version_no, original.version_no)
            self.assertEqual(self.download(original)[1], image_bytes())

    def test_http_upload_and_replacement_never_open_verify_or_decode_with_pillow(self):
        original = self.process(self.upload())
        for kind, suffix in (("PNG", "png"), ("JPEG", "jpeg")):
            content = image_bytes(kind)
            for method, asset in (
                ("post", None),
                ("put", original),
                ("patch", original),
            ):
                with self.subTest(kind=kind, method=method):
                    with patch(
                        "PIL.Image.open",
                        side_effect=AssertionError("Pillow in HTTP path"),
                    ), patch(
                        "PIL.Image.Image.verify",
                        side_effect=AssertionError("verify in HTTP path"),
                    ), patch(
                        "PIL.Image.Image.load",
                        side_effect=AssertionError("decode in HTTP path"),
                    ):
                        response = self.upload(
                            content, f"image.{suffix}", method, asset
                        )
                    self.assertIn(response.status_code, {200, 201}, response.data)
                    self.assertEqual(response.data["processing_status"], "pending")
                    self.assertIsNone(response.data["url"])

    def test_png_is_pending_until_real_decode_and_download_digest_matches(self):
        response = self.upload()
        asset = self.process(response)
        self.assertEqual(self.download(asset)[1], image_bytes())
        self.assertEqual(asset.sha256, hashlib.sha256(image_bytes()).hexdigest())

    def test_pixel_corrupted_png_enters_quarantine_then_is_rejected(self):
        self.process(self.upload(corrupt_png()), "rejected")

    def test_truncated_jpeg_with_valid_frame_header_is_rejected_by_worker(self):
        content = image_bytes("JPEG")
        # Keep every header segment, truncate in the entropy-coded scan.
        scan = content.index(b"\xff\xda")
        self.process(self.upload(content[: scan + 16], "truncated.jpeg"), "rejected")

    def test_pixel_limit_boundaries_without_allocating_large_images(self):
        for width, height, accepted in (
            (5000, 5000, True),
            (5001, 5000, False),
            (0, 3, False),
        ):
            content = change_png_chunk(
                image_bytes(),
                b"IHDR",
                lambda data: struct.pack(">II", width, height) + data[8:],
            )
            with self.subTest(width=width):
                response = self.upload(content)
                self.assertEqual(
                    response.status_code, 201 if accepted else 400, response.data
                )
                # Header-only boundary fixture is deliberately never published.
                if accepted:
                    self.assertIsNone(response.data["url"])

    @override_settings(ASSET_IMAGE_MAX_PIXELS=8)
    def test_lower_worker_pixel_limit_is_enforced(self):
        self.process(self.upload(), "rejected")  # Real 3x3 image exceeds 8 pixels.

    def test_wide_image_below_pixel_limit_is_approved(self):
        output = io.BytesIO()
        Image.new("RGB", (4097, 2), "red").save(output, format="PNG")
        self.process(self.upload(output.getvalue()))

    def test_corrupt_later_apng_frame_is_rejected(self):
        output = io.BytesIO()
        first = Image.new("RGB", (3, 3), "red")
        second = Image.new("RGB", (3, 3), "blue")
        first.save(
            output,
            format="PNG",
            save_all=True,
            append_images=[second],
            duration=100,
            loop=0,
        )
        valid = output.getvalue()
        self.assertIn(b"fdAT", valid)
        self.process(self.upload(valid))
        damaged = change_png_chunk(
            valid, b"fdAT", lambda data: data[:4] + bytes(len(data) - 4)
        )
        self.process(self.upload(damaged), "rejected")

    def test_real_pillow_verifies_and_loads_every_frame(self):
        output = io.BytesIO()
        Image.new("RGB", (3, 3), "red").save(
            output,
            format="PNG",
            save_all=True,
            append_images=[Image.new("RGB", (3, 3), "blue")],
            duration=100,
        )
        response = self.upload(output.getvalue())
        asset = Asset.objects.get(pk=response.data["id"])
        real_open, loaded = Image.open, []
        with patch("PIL.Image.open", wraps=real_open) as opened:
            # Delegate to the real decoder and record the frame after each load.
            from PIL.PngImagePlugin import PngImageFile

            real_load = PngImageFile.load

            def load(image, *args, **kwargs):
                result = real_load(image, *args, **kwargs)
                loaded.append(image.tell())
                return result

            with patch.object(PngImageFile, "load", load):
                self.assertTrue(validate_image(asset.url.name, "png"))
            self.assertEqual(opened.call_count, 2)
        self.assertIn(0, loaded)
        self.assertIn(1, loaded)

    def test_worker_timeout_failure_and_incomplete_results_never_publish(self):
        for outcome in (
            RuntimeError("timeout"),
            (1, {}, False),
            (0, {}, False),
            (0, {"valid": True}, True),
        ):
            with self.subTest(outcome=outcome):
                response = self.upload()
                arguments = (
                    {"side_effect": outcome}
                    if isinstance(outcome, Exception)
                    else {"return_value": outcome}
                )
                with patch("asset.files.run_validation_process", **arguments) as run:
                    self.process(response, "error")
                    self.assertEqual(run.call_args.args[1], 120)
                    self.assertIn("--validate-image", run.call_args.args[0])
                    self.assertIn("-B", run.call_args.args[0])

    def test_timeout_kills_child_and_is_an_operational_failure(self):
        with patch("asset.files.subprocess.Popen") as popen:
            process = popen.return_value.__enter__.return_value
            process.wait.side_effect = [subprocess.TimeoutExpired("image", 120), 0]
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                run_validation_process(["image"], 120)
            process.wait.assert_any_call(timeout=120)
            process.kill.assert_called_once()

    def test_failed_replacement_keeps_approved_historical_file(self):
        original = self.process(self.upload())
        for method in ("put", "patch"):
            replacement = self.process(
                self.upload(corrupt_png(), "bad.png", method, original), "rejected"
            )
            self.assertNotEqual(replacement.pk, original.pk)
            original.refresh_from_db()
            self.assertTrue(original.is_published)
            self.assertEqual(self.download(original)[1], image_bytes())
            self.assertEqual(
                self.client.get("/assets/").data["results"][0]["id"], str(original.pk)
            )

    def test_bounded_headers_reject_malformed_png_and_jpeg(self):
        jpeg = image_bytes("JPEG")
        # Large metadata is skipped, not parsed; excessive marker work is denied.
        padded = jpeg[:2] + (b"\xff\xfe\xff\xff" + bytes(65533)) * 20 + jpeg[2:]
        self.assertEqual(
            validate_file(SimpleUploadedFile("large-header.jpeg", padded)), "jpg"
        )
        for content, name in (
            (jpeg[:2] + b"\xff" * (JPEG_HEADER_MAX_MARKERS + 2) + jpeg[2:], "fill.jpg"),
            (jpeg[:2] + b"\xff\xfe\xff\xff", "length.jpg"),
            (image_bytes()[:29] + bytes(4) + image_bytes()[33:], "crc.png"),
        ):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                validate_file(SimpleUploadedFile(name, content))
