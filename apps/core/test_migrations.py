from django.apps import apps
from django.db.migrations.autodetector import MigrationAutodetector
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.state import ProjectState
from django.test import SimpleTestCase


class MigrationStateTests(SimpleTestCase):
    def test_migration_graph_has_no_conflicting_leaves(self):
        loader = MigrationLoader(None)
        self.assertEqual(loader.detect_conflicts(), {})

    def test_saved_migrations_match_current_models(self):
        loader = MigrationLoader(None)
        pending = MigrationAutodetector(
            loader.project_state(),
            ProjectState.from_apps(apps),
        ).changes(graph=loader.graph)
        descriptions = {
            label: [
                operation.describe()
                for migration in migrations
                for operation in migration.operations
            ]
            for label, migrations in pending.items()
        }
        self.assertEqual(descriptions, {}, "Create migrations for the pending model changes.")
