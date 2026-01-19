"""Management command to validate API migrations."""

import ast
import inspect

from django.core.management.base import BaseCommand, CommandError

from crane.migrations_generator import detect_changes, load_migrations, LoadedMigration
from crane.versioned_api import VersionedNinjaAPI


class Command(BaseCommand):
    help = "Validates API migrations for completeness and correctness."

    def add_arguments(self, parser):
        parser.add_argument(
            "args",
            metavar="api_key",
            nargs="*",
            help=(
                "Specify API(s) as app_label.api_label (e.g., 'myapp.default'). "
                "If omitted, all registered VersionedNinjaAPI instances are validated."
            ),
        )

    def handle(self, *api_keys, **options):
        if api_keys:
            apis = self._resolve_api_keys(api_keys)
        else:
            apis = list(VersionedNinjaAPI.get_registry().values())

        if not apis:
            self.stdout.write(self.style.WARNING("No VersionedNinjaAPI instances found."))
            return

        all_errors: list[str] = []
        all_warnings: list[str] = []

        for api in apis:
            errors, warnings = self._validate_api(api)
            all_errors.extend(errors)
            all_warnings.extend(warnings)

        # Report results
        for warning in all_warnings:
            self.stdout.write(self.style.WARNING(f"Warning: {warning}"))

        for error in all_errors:
            self.stdout.write(self.style.ERROR(f"Error: {error}"))

        if all_errors:
            raise SystemExit(1)

        self.stdout.write(self.style.SUCCESS("All API migrations are valid."))

    def _resolve_api_keys(self, api_keys: tuple[str, ...]) -> list[VersionedNinjaAPI]:
        """Resolve API key strings to VersionedNinjaAPI instances."""
        apis = []
        for key in api_keys:
            parts = key.split(".")
            if len(parts) != 2:
                raise CommandError(f"Invalid API key format: {key}. Use 'app_label.api_label'")
            api = VersionedNinjaAPI.get_api(parts[0], parts[1])
            if not api:
                raise CommandError(f"No VersionedNinjaAPI found with key: {key}")
            apis.append(api)
        return apis

    def _validate_api(self, api: VersionedNinjaAPI) -> tuple[list[str], list[str]]:
        """Validate migrations for a single API."""
        errors: list[str] = []
        warnings: list[str] = []
        key = api.registry_key

        # 1. Check migration chain validity
        try:
            migrations = load_migrations(api.migrations_module)
        except Exception as e:
            errors.append(f"{key}: Failed to load migrations - {e}")
            return errors, warnings

        # 2. Check for pending changes
        try:
            changes = detect_changes(api, api.migrations_module)
            if changes:
                action_count = len(changes.actions)
                errors.append(
                    f"{key}: Pending API changes not captured in migrations "
                    f"({action_count} action(s))"
                )
        except Exception as e:
            errors.append(f"{key}: Failed to detect changes - {e}")

        # 3. Check for NotImplementedError in data migrations
        for m in migrations:
            migration_errors = self._check_migration_implementation(m)
            for err in migration_errors:
                errors.append(f"{key}: {m.file_path.name}: {err}")

        return errors, warnings

    def _check_migration_implementation(self, migration: LoadedMigration) -> list[str]:
        """Check if a migration has unimplemented NotImplementedError."""
        errors: list[str] = []

        if migration.data_migrations is None:
            return errors

        dm = migration.data_migrations

        # Check schema downgrades
        for sd in dm.schema_downgrades:
            if self._has_not_implemented_error(sd.transformer):
                errors.append(f"Schema downgrade for '{sd.schema_ref}' has NotImplementedError")

        # Check schema upgrades
        for su in dm.schema_upgrades:
            if self._has_not_implemented_error(su.transformer):
                errors.append(f"Schema upgrade for '{su.schema_ref}' has NotImplementedError")

        # Check operation downgrades
        for od in dm.operation_downgrades:
            if self._has_not_implemented_error(od.transformer):
                errors.append(
                    f"Operation downgrade for '{od.operation_id}' has NotImplementedError"
                )

        # Check operation upgrades
        for ou in dm.operation_upgrades:
            if self._has_not_implemented_error(ou.transformer):
                errors.append(f"Operation upgrade for '{ou.operation_id}' has NotImplementedError")

        return errors

    def _has_not_implemented_error(self, func) -> bool:
        """Check if a function raises NotImplementedError."""
        try:
            source = inspect.getsource(func)
            tree = ast.parse(source)

            for node in ast.walk(tree):
                if isinstance(node, ast.Raise):
                    if node.exc is not None:
                        # Check for raise NotImplementedError
                        if isinstance(node.exc, ast.Call):
                            if isinstance(node.exc.func, ast.Name):
                                if node.exc.func.id == "NotImplementedError":
                                    return True
                        elif isinstance(node.exc, ast.Name):
                            if node.exc.id == "NotImplementedError":
                                return True
            return False
        except Exception:
            # If we can't inspect the source, assume it's fine
            return False
