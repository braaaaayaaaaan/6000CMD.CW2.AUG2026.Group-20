"""Exercise automatic processing across a real upload transaction and worker."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from user import test_security as accounts
from .models import Asset
from .processing import upload_workers
from .test_security import image_bytes


class AutomaticUploadProcessingTests(TransactionTestCase):
    user = accounts.AccountSecurityTests.user
    login = accounts.AccountSecurityTests.login
    enrol = accounts.AccountSecurityTests.enrol
    sign_in = accounts.AccountSecurityTests.sign_in

    def test_upload_is_validated_by_background_worker_after_commit(self):
        cache.clear()
        for role in ("Viewer", "Editor", "Admin"):
            Group.objects.get_or_create(name=role)
        self.client = APIClient()
        self.sign_in(self.user("upload-worker-editor", role="Editor"))
        with tempfile.TemporaryDirectory() as temporary:
            with override_settings(
                MEDIA_ROOT=str(Path(temporary) / "legacy"),
                ASSET_PRIVATE_ROOT=str(Path(temporary) / "private"),
            ):
                futures = []

                def submit(*args):
                    future = upload_workers.submit(*args)
                    futures.append(future)
                    return future

                with patch("asset.processing.upload_workers") as workers:
                    workers.submit.side_effect = submit
                    response = self.client.post("/assets/", {
                        "name": "Automatic validation",
                        "description": "Worker integration fixture",
                        "url": SimpleUploadedFile("image.png", image_bytes()),
                    }, format="multipart")
                    self.assertEqual(response.status_code, 201, response.data)
                    self.assertEqual(response.data["processing_status"], "pending")
                    self.assertIsNone(response.data["url"])
                    self.assertEqual(len(futures), 1)
                    futures[0].result(timeout=30)
                asset = Asset.objects.get(pk=response.data["id"])
                self.assertTrue(asset.is_published, asset.processing_detail)
                self.assertEqual(asset.processing_attempts, 1)
                self.assertEqual(self.client.get("/assets/").data["count"], 1)
