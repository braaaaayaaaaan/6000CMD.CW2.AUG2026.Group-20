from importlib import import_module
from io import StringIO
from types import SimpleNamespace

from django.apps import apps
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from .models import User
from .serializers import UserSerializer


class SignupGroupTests(TestCase):
    def setUp(self):
        Group.objects.all().delete()
        self.editor = Group.objects.create(id=1, name="Editor")

    def signup(self, **overrides):
        data = {
            "username": "new-viewer",
            "email": "new-viewer@example.com",
            "password1": "Example!LongPassword-4792",
            "password2": "Example!LongPassword-4792",
        }
        data.update(overrides)
        serializer = UserSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    def test_signup_selects_viewer_by_name_even_when_editor_has_id_one(self):
        viewer = Group.objects.create(id=47, name="Viewer")
        user = self.signup(groups=[self.editor.id])
        self.assertEqual(list(user.groups.all()), [viewer])
        self.assertTrue(user.check_password("Example!LongPassword-4792"))

    def test_signup_recovers_missing_viewer_group(self):
        user = self.signup()
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["Viewer"])
        self.assertTrue(Group.objects.filter(name="Editor").exists())


class RequiredGroupTests(TestCase):
    def test_required_groups_are_seeded_by_migrations(self):
        self.assertEqual(set(Group.objects.values_list("name", flat=True)), {"Viewer", "Editor", "Admin"})

    def test_bootstrap_is_repeatable_and_preserves_memberships_and_permissions(self):
        viewer = Group.objects.get(name="Viewer")
        viewer.permissions.add(Permission.objects.first())
        user = User.objects.create_user(username="existing-viewer")
        user.groups.add(viewer)
        ids = dict(Group.objects.values_list("name", "id"))
        for _ in range(2):
            call_command("bootstrap_groups", stdout=StringIO())
        self.assertEqual(dict(Group.objects.values_list("name", "id")), ids)
        self.assertTrue(user.groups.filter(id=viewer.id).exists())
        self.assertEqual(viewer.permissions.count(), 1)

    def test_group_seed_can_be_repeated_without_deleting_existing_groups(self):
        Group.objects.filter(name="Editor").delete()
        other = Group.objects.create(name="Team-specific")
        migration = import_module("user.migrations.0002_required_groups")
        editor = SimpleNamespace(connection=connection)
        migration.create_required_groups(apps, editor)
        migration.create_required_groups(apps, editor)
        self.assertTrue(Group.objects.filter(id=other.id).exists())
        self.assertEqual(Group.objects.filter(name__in=["Viewer", "Editor"]).count(), 2)
