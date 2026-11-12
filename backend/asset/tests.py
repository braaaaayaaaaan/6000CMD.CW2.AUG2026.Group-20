import uuid
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.db.backends.postgresql.base import DatabaseWrapper
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder
from django.test import SimpleTestCase, TestCase

from .models import Asset, Tags


REPLACEMENT = ("asset", "0001_squashed_0010_fresh_schema")
LEGACY_LEAF = ("asset", "0010_asset_version_no")


class AssetMigrationGraphTests(SimpleTestCase):
    def test_replacement_has_identical_final_state_to_original_history(self):
        original = MigrationLoader(None, replace_migrations=False)
        fresh = MigrationLoader(None)
        self.assertEqual(
            original.project_state([LEGACY_LEAF]),
            fresh.project_state([REPLACEMENT]),
        )
        self.assertEqual(fresh.graph.leaf_nodes("asset"), [
            ("asset", "0011_assetseries_asset_unique_asset_version_and_more"),
        ])

    def test_partial_history_keeps_original_graph_for_explicit_review(self):
        applied = {("asset", "0001_initial"): object(), ("asset", "0002_tags"): object()}
        with patch.object(MigrationRecorder, "applied_migrations", return_value=applied):
            loader = MigrationLoader(connection)
        self.assertNotIn(REPLACEMENT, loader.graph.nodes)
        self.assertIn(("asset", "0003_alter_tags_id"), loader.graph.nodes)

    def test_postgresql_ddl_creates_uuid_keys_without_connecting(self):
        state = MigrationLoader(None).project_state([REPLACEMENT])
        postgres = DatabaseWrapper({
            "ENGINE": "django.db.backends.postgresql",
            "NAME": "unused", "USER": "unused", "PASSWORD": "unused",
            "HOST": "unused.invalid", "PORT": "5432", "OPTIONS": {},
            "TIME_ZONE": None, "AUTOCOMMIT": True,
        }, alias="offline_postgresql")
        # Only SQL generation is under test; never open a socket.
        postgres.__dict__["pg_version"] = 170000
        with patch.object(postgres, "ensure_connection", side_effect=AssertionError("Offline SQL test attempted a connection")):
            with postgres.schema_editor(collect_sql=True, atomic=False) as editor:
                for name in ("Tags", "UniqueCodeGenerator", "Asset"):
                    editor.create_model(state.apps.get_model("asset", name))
        sql = "\n".join(editor.collected_sql)
        self.assertIn('CREATE TABLE "asset_tags" ("id" uuid', sql)
        self.assertIn('CREATE TABLE "asset_asset_tags"', sql)
        self.assertNotIn("::uuid", sql)
        self.assertNotIn('DROP TABLE', sql)


class AssetSchemaTests(TestCase):
    def create_asset(self):
        return Asset.objects.create(
            name="Example", description="Migration regression test",
            uploaded_by="test-user", file_type="png", file_size=1,
            url="uploads/example.png",
        )

    def test_fresh_schema_supports_uuid_relationships_and_code_sequence(self):
        tag = Tags.objects.create(title="Example")
        asset = self.create_asset()
        asset.tags.add(tag)
        asset.refresh_from_db()
        self.assertIsInstance(tag.id, uuid.UUID)
        self.assertIsInstance(asset.id, uuid.UUID)
        self.assertEqual(list(asset.tags.values_list("id", flat=True)), [tag.id])
        self.assertNotEqual(asset.code, self.create_asset().code)

    def test_fully_applied_legacy_history_does_not_recreate_tables_or_records(self):
        tag = Tags.objects.create(title="Preserved")
        asset = self.create_asset()
        asset.tags.add(tag)
        # Emulate a teammate with the same final schema and original history,
        # without the replacement marker. This is confined to the test database.
        recorder = MigrationRecorder(connection)
        recorder.record_unapplied(*REPLACEMENT)
        replacement = MigrationLoader(None).disk_migrations[REPLACEMENT]
        applied = recorder.applied_migrations()
        for app_label, name in replacement.replaces:
            if (app_label, name) not in applied:
                recorder.record_applied(app_label, name)
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        self.assertFalse(any(migration.app_label == "asset" for migration, _ in plan))
        call_command("migrate", verbosity=0)
        self.assertTrue(Tags.objects.filter(id=tag.id, title="Preserved").exists())
        self.assertTrue(asset.tags.filter(id=tag.id).exists())
        self.assertIn(REPLACEMENT, MigrationRecorder(connection).applied_migrations())
