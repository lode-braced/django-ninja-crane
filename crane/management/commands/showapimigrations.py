"""Management command to show API migration status."""

from django.core.management.base import BaseCommand, CommandError

from crane.migrations_generator import detect_changes, load_migrations
from crane.versioned_api import VersionedNinjaAPI


class Command(BaseCommand):
    help = "Shows all API migrations for versioned APIs."

    def add_arguments(self, parser):
        parser.add_argument(
            "args",
            metavar="api_key",
            nargs="*",
            help=(
                "Specify API(s) as app_label.api_label (e.g., 'myapp.default'). "
                "If omitted, all registered VersionedNinjaAPI instances are shown."
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

        for api in apis:
            self._show_api_migrations(api)

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

    def _show_api_migrations(self, api: VersionedNinjaAPI) -> None:
        """Display migration status for a single API."""
        self.stdout.write(self.style.MIGRATE_LABEL(f"{api.registry_key}:"))

        try:
            migrations = load_migrations(api.migrations_module)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  Error loading migrations: {e}"))
            return

        if not migrations:
            self.stdout.write("  (no migrations)")
        else:
            for m in migrations:
                self.stdout.write(f"  [X] {m.file_path.name} ({m.to_version})")

        # Check for pending changes
        try:
            changes = detect_changes(api, api.migrations_module)
            if changes:
                action_count = len(changes.actions)
                self.stdout.write(
                    self.style.WARNING(
                        f"  [ ] (pending changes detected: {action_count} action(s))"
                    )
                )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  Error detecting changes: {e}"))
