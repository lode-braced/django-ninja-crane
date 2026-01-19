"""Management command to create API migrations."""

from django.core.management.base import BaseCommand, CommandError

from crane.delta import (
    OperationAdded,
    OperationModified,
    OperationRemoved,
    SchemaDefinitionAdded,
    SchemaDefinitionModified,
    SchemaDefinitionRemoved,
    VersionDelta,
)
from crane.migrations_generator import (
    _slugify,
    detect_changes,
    generate_migration,
)
from crane.versioned_api import VersionedNinjaAPI


class Command(BaseCommand):
    help = "Creates new API migration(s) for versioned APIs."

    def add_arguments(self, parser):
        parser.add_argument(
            "args",
            metavar="api_key",
            nargs="*",
            help=(
                "Specify API(s) as app_label.api_label (e.g., 'myapp.default'). "
                "If omitted, all registered VersionedNinjaAPI instances are checked."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what migrations would be created without writing them.",
        )
        parser.add_argument(
            "-n",
            "--name",
            help="Migration description/name (e.g., 'Add users endpoint').",
        )
        parser.add_argument(
            "--version-name",
            dest="version_name",
            help="Version name (required for manual versioning, optional otherwise).",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help="Exit with non-zero status if changes are missing migrations.",
        )

    def handle(self, *api_keys, **options):
        if api_keys:
            apis = self._resolve_api_keys(api_keys)
        else:
            apis = list(VersionedNinjaAPI.get_registry().values())

        if not apis:
            self.stdout.write(self.style.WARNING("No VersionedNinjaAPI instances found."))
            return

        dry_run = options["dry_run"]
        check_mode = options["check"]
        has_changes = False

        for api in apis:
            try:
                changes = detect_changes(api, api.migrations_module)
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Error detecting changes for {api.registry_key}: {e}")
                )
                continue

            if not changes:
                self.stdout.write(f"No changes detected for {api.registry_key}")
                continue

            has_changes = True

            # Determine version name
            version_name = options.get("version_name")
            if not version_name:
                try:
                    version_name = api.generate_next_version()
                except ValueError as e:
                    raise CommandError(str(e))

            # Determine description
            description = options.get("name") or self._generate_description(changes)

            self.stdout.write(self.style.MIGRATE_HEADING(f"Migrations for '{api.registry_key}':"))

            # Show changes summary
            self._display_changes(changes)

            if dry_run or check_mode:
                slug = _slugify(description)
                self.stdout.write(f"  Would create: m_XXXX_{slug}.py (version {version_name})")
            else:
                try:
                    result = generate_migration(
                        api,
                        api.migrations_module,
                        version_name,
                        description,
                    )
                    if result:
                        self.stdout.write(self.style.SUCCESS(f"  Created: {result}"))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"  Error creating migration: {e}"))

        if check_mode and has_changes:
            raise SystemExit(1)

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

    def _generate_description(self, delta: VersionDelta) -> str:
        """Generate a description from the delta's actions."""
        action_types: dict[str, int] = {}

        for action in delta.actions:
            if isinstance(action, OperationAdded):
                action_types["operations added"] = action_types.get("operations added", 0) + 1
            elif isinstance(action, OperationRemoved):
                action_types["operations removed"] = action_types.get("operations removed", 0) + 1
            elif isinstance(action, OperationModified):
                action_types["operations modified"] = action_types.get("operations modified", 0) + 1
            elif isinstance(action, SchemaDefinitionAdded):
                action_types["schemas added"] = action_types.get("schemas added", 0) + 1
            elif isinstance(action, SchemaDefinitionRemoved):
                action_types["schemas removed"] = action_types.get("schemas removed", 0) + 1
            elif isinstance(action, SchemaDefinitionModified):
                action_types["schemas modified"] = action_types.get("schemas modified", 0) + 1

        if not action_types:
            return "api_changes"

        # Build a summary like "2 operations added, 1 schema modified"
        parts = [f"{count} {desc}" for desc, count in action_types.items()]
        return ", ".join(parts[:3])  # Limit to 3 for filename length

    def _display_changes(self, delta: VersionDelta) -> None:
        """Display a summary of changes."""
        for action in delta.actions:
            if isinstance(action, OperationAdded):
                self.stdout.write(
                    self.style.SUCCESS(f"    + Operation: {action.method.upper()} {action.path}")
                )
            elif isinstance(action, OperationRemoved):
                self.stdout.write(
                    self.style.ERROR(f"    - Operation: {action.method.upper()} {action.path}")
                )
            elif isinstance(action, OperationModified):
                self.stdout.write(
                    self.style.WARNING(f"    ~ Operation: {action.method.upper()} {action.path}")
                )
            elif isinstance(action, SchemaDefinitionAdded):
                schema_name = action.schema_ref.rsplit("/", 1)[-1]
                self.stdout.write(self.style.SUCCESS(f"    + Schema: {schema_name}"))
            elif isinstance(action, SchemaDefinitionRemoved):
                schema_name = action.schema_ref.rsplit("/", 1)[-1]
                self.stdout.write(self.style.ERROR(f"    - Schema: {schema_name}"))
            elif isinstance(action, SchemaDefinitionModified):
                schema_name = action.schema_ref.rsplit("/", 1)[-1]
                self.stdout.write(self.style.WARNING(f"    ~ Schema: {schema_name}"))
