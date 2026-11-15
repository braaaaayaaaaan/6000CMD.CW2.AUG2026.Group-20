"""Create only synthetic ZAP fixtures; never runs under development settings."""
import io
import json
import secrets

from PIL import Image
from django.conf import settings
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError

from backend.zap_safety import STATE, assert_isolated, safe_path


class Command(BaseCommand):
    help = "Seed disposable Viewer/Editor/Admin accounts and validated image assets."

    def handle(self, *args, **options):
        if not getattr(settings, "ZAP_ISOLATED", False):
            raise CommandError("seed_zap requires the dedicated ZAP launcher.")
        assert_isolated(settings)
        from user.models import User
        from user.security import reserve_email
        from asset.models import Asset, Tags
        from asset.serializers import AssetSerializer
        from asset.files import staged_file, process_uploads
        credentials = safe_path(STATE / "accounts.json")
        if credentials.exists():
            self.stdout.write("ZAP fixture credentials already exist; use reset for a fresh data set.")
            return
        if User.objects.exists() or Asset.objects.exists():
            raise CommandError("Refusing to seed over existing isolated records; use reset.")
        accounts = []
        for role in ("Viewer", "Editor", "Admin"):
            password = secrets.token_urlsafe(24) + "!aA9"
            user = User.objects.create_user(
                username="zap_" + role.lower(), email=f"zap_{role.lower()}@example.invalid",
                password=password, email_verified=True, is_staff=role == "Admin",
                is_superuser=False,
            )
            group, _ = Group.objects.get_or_create(name=role)
            user.groups.add(group)
            reserve_email(user)
            accounts.append({"username": user.username, "password": password, "role": role,
                             "email": user.email, "mfa": "Enrol through the normal first-login flow."})
        tag, _ = Tags.objects.get_or_create(title="ZAP disposable")
        for name, color in (("ZAP red sample", "red"), ("ZAP blue sample", "blue")):
            output = io.BytesIO()
            Image.new("RGB", (48, 48), color).save(output, "PNG")
            payload = output.getvalue()
            sample = STATE / (name.replace(" ", "-").lower() + ".png")
            safe_path(sample).write_bytes(payload)
            serializer = AssetSerializer(data={"name": name, "description": "Synthetic disposable security test image.",
                "url": SimpleUploadedFile("sample.png", payload, content_type="image/png")})
            serializer.is_valid(raise_exception=True)
            with staged_file(serializer):
                asset = serializer.save(uploaded_by="zap_editor")
                asset.tags.add(tag)
            # Uses the production decoder subprocess, quarantine promotion and SHA-256 checks.
            process_uploads(limit=1, asset_id=asset.pk)
            asset.refresh_from_db()
            if not asset.is_published:
                raise CommandError("Synthetic asset failed the existing validation pipeline.")
        with credentials.open("x", encoding="utf-8") as file:
            json.dump(accounts, file, indent=2)
        credentials.chmod(0o600)
        self.stdout.write("Created three role accounts (MFA enrolment required), two validated PNG assets and one tag.")
