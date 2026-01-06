"""Automatic API schema migration generation.

This module provides functionality to auto-generate migration files for Django Ninja APIs,
similar to Django's makemigrations. It detects changes between the current API state and
stored migrations, then generates new migration files with the detected delta.
"""

from __future__ import annotations

import importlib
import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path

from ninja import NinjaAPI

from crane.api_version import ApiVersion, create_api_version
from crane.delta import VersionDelta, apply_delta_forwards, create_delta

type MigrationRef = tuple[str, str]  # (module_path, version_name)


# === Exceptions ===


class MigrationError(Exception):
    """Base exception for migration errors."""


class MigrationLoadError(MigrationError):
    """Failed to load migrations."""


class MigrationChainError(MigrationError):
    """Migration chain is broken (dependency mismatch)."""


class MigrationGenerationError(MigrationError):
    """Failed to generate migration."""


# === Data Models ===


@dataclass
class LoadedMigration:
    """Represents a loaded migration file."""

    sequence: int
    slug: str
    file_path: Path
    dependencies: list[MigrationRef]
    from_version: str | None
    to_version: str
    delta: VersionDelta


# === Helper Functions ===


def _parse_migration_filename(filename: str) -> tuple[int, str] | None:
    """Parse 'm_0001_initial.py' -> (1, 'initial') or None if invalid."""
    match = re.match(r"^m_(\d{4})_(.+)\.py$", filename)
    if match:
        return int(match.group(1)), match.group(2)
    return None


def _slugify(name: str, max_length: int = 50) -> str:
    """Convert user-provided name to a valid Python identifier slug.

    'Add Users Endpoint' -> 'add_users_endpoint'
    'v2.0-release!' -> 'v20_release'
    """
    # Lowercase and replace spaces/hyphens with underscores
    slug = name.lower().replace(" ", "_").replace("-", "_")
    # Remove non-alphanumeric characters (except underscores)
    slug = re.sub(r"[^a-z0-9_]", "", slug)
    # Collapse multiple underscores
    slug = re.sub(r"_+", "_", slug)
    # Strip leading/trailing underscores
    slug = slug.strip("_")
    # Truncate to max length, avoiding cutting mid-word if possible
    if len(slug) > max_length:
        truncated = slug[:max_length]
        # Try to cut at last underscore to avoid mid-word truncation
        last_underscore = truncated.rfind("_")
        if last_underscore > max_length // 2:
            truncated = truncated[:last_underscore]
        slug = truncated.rstrip("_")
    return slug or "migration"


def _module_to_path(migrations_module: str) -> Path:
    """Convert a module path to filesystem path.

    'myapp.api_migrations' -> Path('/path/to/myapp/api_migrations')
    """
    spec = importlib.util.find_spec(migrations_module)
    if spec is None or spec.origin is None:
        # Module doesn't exist yet, try to find parent
        parts = migrations_module.rsplit(".", 1)
        if len(parts) == 2:
            parent_module, submodule = parts
            parent_spec = importlib.util.find_spec(parent_module)
            if parent_spec and parent_spec.submodule_search_locations:
                return Path(parent_spec.submodule_search_locations[0]) / submodule
        raise MigrationGenerationError(f"Cannot resolve module path: {migrations_module}")

    # Module exists, return its directory
    origin = Path(spec.origin)
    if origin.name == "__init__.py":
        return origin.parent
    return origin.parent / migrations_module.rsplit(".", 1)[-1]


def _get_next_sequence(migrations: list[LoadedMigration]) -> int:
    """Get the next sequence number (max + 1, or 1 if empty)."""
    if not migrations:
        return 1
    return max(m.sequence for m in migrations) + 1


def _ensure_migrations_package(migrations_path: Path) -> None:
    """Ensure the migrations directory exists with __init__.py."""
    migrations_path.mkdir(parents=True, exist_ok=True)
    init_file = migrations_path / "__init__.py"
    if not init_file.exists():
        init_file.write_text("")


# === Core Functions ===


def load_migrations(migrations_module: str) -> list[LoadedMigration]:
    """Load all migrations from a module path.

    Args:
        migrations_module: Dotted module path (e.g., "myapp.api_migrations")

    Returns:
        List of LoadedMigration sorted by sequence number.

    Raises:
        MigrationLoadError: If migrations cannot be loaded or are invalid.
        MigrationChainError: If migration chain is broken.
    """
    try:
        module = importlib.import_module(migrations_module)
    except ModuleNotFoundError:
        return []  # No migrations yet

    if not hasattr(module, "__file__") or module.__file__ is None:
        return []

    module_path = Path(module.__file__).parent
    migrations: list[LoadedMigration] = []

    for file_path in module_path.glob("m_*.py"):
        parsed = _parse_migration_filename(file_path.name)
        if parsed is None:
            continue

        sequence, slug = parsed

        # Import the migration module
        spec = importlib.util.spec_from_file_location(
            f"{migrations_module}.{file_path.stem}", file_path
        )
        if spec is None or spec.loader is None:
            raise MigrationLoadError(f"Cannot load migration: {file_path}")

        migration_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration_module)

        # Extract required attributes
        dependencies = getattr(migration_module, "dependencies", [])
        from_version = getattr(migration_module, "from_version", None)
        to_version = getattr(migration_module, "to_version", None)
        delta = getattr(migration_module, "delta", None)

        if to_version is None:
            raise MigrationLoadError(
                f"Migration {file_path} missing required 'to_version' attribute"
            )
        if delta is None:
            raise MigrationLoadError(f"Migration {file_path} missing required 'delta' attribute")

        migrations.append(
            LoadedMigration(
                sequence=sequence,
                slug=slug,
                file_path=file_path,
                dependencies=dependencies,
                from_version=from_version,
                to_version=to_version,
                delta=delta,
            )
        )

    migrations.sort(key=lambda m: m.sequence)
    _validate_chain(migrations, migrations_module)
    return migrations


def _validate_chain(migrations: list[LoadedMigration], migrations_module: str) -> None:
    """Validate that migration dependencies form a valid chain."""
    if not migrations:
        return

    # Build a set of available versions
    available_versions: set[MigrationRef] = set()
    for m in migrations:
        # Check that all dependencies are satisfied
        for dep in m.dependencies:
            if dep not in available_versions:
                raise MigrationChainError(
                    f"Migration {m.file_path.name} depends on {dep!r} which is not available"
                )
        # Add this migration's version to available
        available_versions.add((migrations_module, m.to_version))


def get_known_api_state(migrations: list[LoadedMigration]) -> ApiVersion:
    """Reconstruct the API state by applying all migrations forwards from empty.

    Args:
        migrations: Ordered list of migrations to apply.

    Returns:
        The reconstructed ApiVersion.
    """
    state = ApiVersion(path_operations={}, schema_definitions={})
    for m in migrations:
        state = apply_delta_forwards(state, m.delta)
    return state


def detect_changes(api: NinjaAPI, migrations_module: str) -> VersionDelta | None:
    """Detect changes between known migration state and current API.

    Args:
        api: The current NinjaAPI instance.
        migrations_module: Module path to migrations.

    Returns:
        VersionDelta with detected changes, or None if no changes.
    """
    migrations = load_migrations(migrations_module)
    known_state = get_known_api_state(migrations)
    current_state = create_api_version(api)
    delta = create_delta(known_state, current_state)

    if not delta.actions:
        return None
    return delta


def render_migration_file(
    dependencies: list[MigrationRef],
    from_version: str | None,
    to_version: str,
    description: str,
    delta: VersionDelta,
) -> str:
    """Generate Python source code for migration file."""
    delta_json = delta.model_dump_json(indent=4)

    from_desc = from_version or "empty"
    deps_repr = repr(dependencies)

    return f'''
"""
API migration: {from_desc} -> {to_version}

{description}
"""
from crane.delta import VersionDelta

dependencies: list[tuple[str, str]] = {deps_repr}
from_version: str | None = {from_version!r}
to_version: str = {to_version!r}

delta = VersionDelta.model_validate_json("""
{delta_json}
""")
'''


def generate_migration(
    api: NinjaAPI,
    migrations_module: str,
    version_name: str,
    description: str,
) -> Path | None:
    """Generate a new migration file if changes are detected.

    Args:
        api: The current NinjaAPI instance.
        migrations_module: Module path to migrations.
        version_name: The API version identifier (e.g., "v1", "v2", "2024-01-15").
        description: Human-readable description of what the migration does,
                     used for the filename slug (e.g., "Add users endpoint").

    Returns:
        Path to generated file, or None if no changes detected.

    Raises:
        MigrationGenerationError: If migration cannot be generated.
    """
    migrations = load_migrations(migrations_module)
    known_state = get_known_api_state(migrations)
    current_state = create_api_version(api)
    delta = create_delta(known_state, current_state)

    if not delta.actions:
        return None

    # Determine from_version and dependencies
    if migrations:
        from_version = migrations[-1].to_version
        dependencies: list[MigrationRef] = [(migrations_module, from_version)]
    else:
        from_version = None
        dependencies = []

    # Generate file
    sequence = _get_next_sequence(migrations)
    slug = _slugify(description)
    filename = f"m_{sequence:04d}_{slug}.py"

    content = render_migration_file(dependencies, from_version, version_name, description, delta)

    migrations_path = _module_to_path(migrations_module)
    _ensure_migrations_package(migrations_path)

    file_path = migrations_path / filename
    file_path.write_text(content)

    return file_path
