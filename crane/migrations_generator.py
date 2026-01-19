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
from typing import cast

from ninja import NinjaAPI

from crane.api_version import ApiVersion, create_api_version
from crane.data_migrations import DataMigrationSet
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
    data_migrations: DataMigrationSet | None = None


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

    Supports nested module paths:
    - 'myapp.api_migrations' -> Path('/path/to/myapp/api_migrations')
    - 'myapp.api_migrations.default' -> Path('/path/to/myapp/api_migrations/default')
    """
    spec = importlib.util.find_spec(migrations_module)
    if spec is not None and spec.origin is not None:
        # Module exists, return its directory
        origin = Path(spec.origin)
        if origin.name == "__init__.py":
            return origin.parent
        return origin.parent / migrations_module.rsplit(".", 1)[-1]

    # Module doesn't exist yet, try to find parent recursively
    parts = migrations_module.rsplit(".", 1)
    if len(parts) == 2:
        parent_module, submodule = parts
        try:
            parent_path = _module_to_path(parent_module)
            return parent_path / submodule
        except MigrationGenerationError:
            pass

    raise MigrationGenerationError(f"Cannot resolve module path: {migrations_module}")


def _get_next_sequence(migrations: list[LoadedMigration]) -> int:
    """Get the next sequence number (max + 1, or 1 if empty)."""
    if not migrations:
        return 1
    return max(m.sequence for m in migrations) + 1


def _ensure_migrations_package(migrations_path: Path) -> None:
    """Ensure the migrations directory exists with __init__.py at each level.

    For nested paths like 'myapp/api_migrations/default/', creates __init__.py
    in both 'api_migrations/' and 'api_migrations/default/'.
    """
    migrations_path.mkdir(parents=True, exist_ok=True)

    # Create __init__.py files at each level that needs one
    # Walk up from the target path until we hit an existing __init__.py or package
    current = migrations_path
    init_files_needed: list[Path] = []

    while current.name:  # Stop at filesystem root
        init_file = current / "__init__.py"
        if init_file.exists():
            break
        # Check if parent has __init__.py (we're inside a package)
        parent_init = current.parent / "__init__.py"
        if not parent_init.exists():
            break
        init_files_needed.append(init_file)
        current = current.parent

    # Create the __init__.py files
    for init_file in init_files_needed:
        if not init_file.exists():
            init_file.write_text("")

    # Always ensure the target directory has __init__.py
    target_init = migrations_path / "__init__.py"
    if not target_init.exists():
        target_init.write_text("")


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
        data_migrations = getattr(migration_module, "data_migrations", None)

        if to_version is None:
            raise MigrationLoadError(
                f"Migration {file_path} missing required 'to_version' attribute"
            )
        if delta is None:
            raise MigrationLoadError(f"Migration {file_path} missing required 'delta' attribute")

        # Validate data_migrations type if present
        if data_migrations is not None and not isinstance(data_migrations, DataMigrationSet):
            raise MigrationLoadError(
                f"Migration {file_path} has invalid 'data_migrations' (expected DataMigrationSet)"
            )

        migrations.append(
            LoadedMigration(
                sequence=sequence,
                slug=slug,
                file_path=file_path,
                dependencies=dependencies,
                from_version=from_version,
                to_version=to_version,
                delta=delta,
                data_migrations=data_migrations,
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


# === Skeleton Generation ===


def _schema_ref_to_name(schema_ref: str) -> str:
    """Convert '#/components/schemas/PersonOut' to 'person_out'."""
    name = schema_ref.rsplit("/", 1)[-1]
    # Convert CamelCase to snake_case
    result = []
    for i, char in enumerate(name):
        if char.isupper() and i > 0:
            result.append("_")
        result.append(char.lower())
    return "".join(result)


def _analyze_schema_change(
    old_schema: dict[str, object],
    new_schema: dict[str, object],
) -> tuple[list[tuple[str, object]], list[str], bool]:
    """Analyze a schema modification to determine what changed.

    Returns:
        - added_fields: list of (field_name, field_schema) for new fields
        - removed_fields: list of field names that were removed
        - has_breaking_changes: True if there are type changes or other breaking modifications
    """
    old_props_val = old_schema.get("properties", {})
    new_props_val = new_schema.get("properties", {})
    old_props = cast(dict[str, object], old_props_val if isinstance(old_props_val, dict) else {})
    new_props = cast(dict[str, object], new_props_val if isinstance(new_props_val, dict) else {})
    old_required_val = old_schema.get("required", [])
    new_required_val = new_schema.get("required", [])
    old_required = cast(
        set[str], set(old_required_val) if isinstance(old_required_val, list) else set()
    )
    new_required = cast(
        set[str], set(new_required_val) if isinstance(new_required_val, list) else set()
    )

    added_fields: list[tuple[str, object]] = []
    removed_fields: list[str] = []
    has_breaking_changes = False

    # Check for non-property changes (type, title, etc.)
    for key in set(old_schema.keys()) | set(new_schema.keys()):
        if key in ("properties", "required"):
            continue
        if old_schema.get(key) != new_schema.get(key):
            has_breaking_changes = True

    # Analyze property changes
    old_field_names = set(old_props.keys())
    new_field_names = set(new_props.keys())

    for field_name in new_field_names - old_field_names:
        field_schema = new_props.get(field_name, {})
        # Check if it's a new required field (breaking)
        if field_name in new_required:
            has_breaking_changes = True
        added_fields.append((field_name, field_schema))

    for field_name in old_field_names - new_field_names:
        removed_fields.append(field_name)

    # Check for modified fields (type changes are breaking)
    for field_name in old_field_names & new_field_names:
        if old_props.get(field_name) != new_props.get(field_name):
            has_breaking_changes = True

    # New required constraint on existing field is breaking
    newly_required = (new_required - old_required) & old_field_names
    if newly_required:
        has_breaking_changes = True

    return added_fields, removed_fields, has_breaking_changes


def _get_field_default(field_schema: object) -> str | None:
    """Extract default value from field schema, return Python repr or None."""
    if not isinstance(field_schema, dict):
        return None
    schema = cast(dict[str, object], field_schema)
    default = schema.get("default")
    if default is not None:
        return repr(default)
    # For optional fields (nullable), None is a safe default
    any_of = schema.get("anyOf")
    if any_of and isinstance(any_of, list):
        for option in any_of:
            if isinstance(option, dict):
                opt = cast(dict[str, object], option)
                if opt.get("type") == "null":
                    return "None"
    return None


def _generate_downgrade_function(
    schema_name: str,
    added_fields: list[tuple[str, object]],
    removed_fields: list[str],
    has_breaking_changes: bool,
    from_version: str | None,
    to_version: str,
) -> str:
    """Generate a downgrade transformer function."""
    func_name = f"downgrade_{schema_name}"
    from_desc = from_version or "initial"

    lines = [
        f"def {func_name}(data: dict) -> dict:",
        f'    """{to_version} -> {from_desc}: Transform {schema_name} for older clients."""',
    ]

    if has_breaking_changes and not added_fields and not removed_fields:
        lines.append(
            '    raise NotImplementedError("Breaking schema change requires manual implementation")'
        )
    elif not added_fields and not removed_fields:
        lines.append("    return data  # No field changes to transform")
    else:
        # Remove fields that were added in new version
        for field_name, _ in added_fields:
            lines.append(f'    data.pop("{field_name}", None)')

        # Add back fields that were removed in new version (need defaults)
        for field_name in removed_fields:
            lines.append(
                f'    raise NotImplementedError("Provide default value for removed field: {field_name}")'
            )
            lines.append(f'    # data.setdefault("{field_name}", <default_value>)')

        if not removed_fields:
            lines.append("    return data")

    return "\n".join(lines)


def _generate_upgrade_function(
    schema_name: str,
    added_fields: list[tuple[str, object]],
    removed_fields: list[str],
    has_breaking_changes: bool,
    from_version: str | None,
    to_version: str,
) -> str:
    """Generate an upgrade transformer function."""
    func_name = f"upgrade_{schema_name}"
    from_desc = from_version or "initial"

    lines = [
        f"def {func_name}(data: dict) -> dict:",
        f'    """{from_desc} -> {to_version}: Transform {schema_name} from older clients."""',
    ]

    if has_breaking_changes and not added_fields and not removed_fields:
        lines.append(
            '    raise NotImplementedError("Breaking schema change requires manual implementation")'
        )
    elif not added_fields and not removed_fields:
        lines.append("    return data  # No field changes to transform")
    else:
        needs_not_implemented = False

        # Add fields that are new in the current version (for incoming requests)
        for field_name, field_schema in added_fields:
            default = _get_field_default(field_schema)
            if default is not None:
                lines.append(f'    data.setdefault("{field_name}", {default})')
            else:
                needs_not_implemented = True
                lines.append(
                    f'    raise NotImplementedError("Provide default value for new field: {field_name}")'
                )
                lines.append(f'    # data.setdefault("{field_name}", <default_value>)')

        # Remove fields that don't exist in current version
        for field_name in removed_fields:
            lines.append(f'    data.pop("{field_name}", None)')

        if not needs_not_implemented:
            lines.append("    return data")

    return "\n".join(lines)


def _detect_path_renames(
    delta: VersionDelta,
) -> list[tuple[str, str, str]]:
    """Detect path renames by matching operation_id across removed/added operations.

    Returns list of (old_path, new_path, method) tuples for detected renames.
    """
    from crane.delta import OperationAdded, OperationRemoved

    # Collect removed and added operations
    removed: dict[tuple[str, str], str] = {}  # (operation_id, method) -> old_path
    added: dict[tuple[str, str], str] = {}  # (operation_id, method) -> new_path

    for action in delta.actions:
        if isinstance(action, OperationRemoved):
            op_id = action.old_operation.operation_id
            removed[(op_id, action.method)] = action.path
        elif isinstance(action, OperationAdded):
            op_id = action.new_operation.operation_id
            added[(op_id, action.method)] = action.path

    # Find matches - same operation_id and method but different paths
    renames: list[tuple[str, str, str]] = []
    for key, old_path in removed.items():
        if key in added:
            new_path = added[key]
            if old_path != new_path:
                op_id, method = key
                renames.append((old_path, new_path, method))

    return renames


def generate_data_migrations_code(
    delta: VersionDelta,
    from_version: str | None,
    to_version: str,
) -> str | None:
    """Generate data migration skeleton code from a delta.

    Returns None if no data migrations are needed (e.g., only operation additions).
    """
    from crane.delta import SchemaDefinitionAdded, SchemaDefinitionModified, SchemaDefinitionRemoved

    downgrade_functions: list[str] = []
    upgrade_functions: list[str] = []
    schema_downgrades: list[str] = []
    schema_upgrades: list[str] = []
    path_rewrites: list[str] = []

    # Detect path renames (same operation_id, different path)
    renames = _detect_path_renames(delta)
    for old_path, new_path, method in renames:
        path_rewrites.append(
            f'    PathRewrite(old_path="{old_path}", new_path="{new_path}", methods=["{method}"]),'
        )

    for action in delta.actions:
        if isinstance(action, SchemaDefinitionModified):
            schema_name = _schema_ref_to_name(action.schema_ref)
            old_schema = cast(
                dict[str, object],
                action.old_schema if isinstance(action.old_schema, dict) else {},
            )
            new_schema = cast(
                dict[str, object],
                action.new_schema if isinstance(action.new_schema, dict) else {},
            )

            added_fields, removed_fields, has_breaking = _analyze_schema_change(
                old_schema, new_schema
            )

            # Generate downgrade (new -> old)
            downgrade_func = _generate_downgrade_function(
                schema_name, added_fields, removed_fields, has_breaking, from_version, to_version
            )
            downgrade_functions.append(downgrade_func)
            schema_downgrades.append(
                f'    SchemaDowngrade("{action.schema_ref}", downgrade_{schema_name}),'
            )

            # Generate upgrade (old -> new)
            upgrade_func = _generate_upgrade_function(
                schema_name, added_fields, removed_fields, has_breaking, from_version, to_version
            )
            upgrade_functions.append(upgrade_func)
            schema_upgrades.append(
                f'    SchemaUpgrade("{action.schema_ref}", upgrade_{schema_name}),'
            )

        elif isinstance(action, SchemaDefinitionAdded):
            # New schema - need downgrade to remove it from responses
            schema_name = _schema_ref_to_name(action.schema_ref)

            # Extract field names for removal
            new_schema = action.new_schema if isinstance(action.new_schema, dict) else {}
            props = new_schema.get("properties", {})
            field_names = list(props.keys()) if isinstance(props, dict) else []

            func_lines = [
                f"def downgrade_{schema_name}(data: dict) -> dict:",
                f'    """{to_version} -> {from_version or "initial"}: Remove new schema from responses."""',
            ]
            if field_names:
                for field_name in field_names:
                    func_lines.append(f'    data.pop("{field_name}", None)')
                func_lines.append("    return data")
            else:
                func_lines.append("    return {}  # Schema didn't exist in previous version")

            downgrade_functions.append("\n".join(func_lines))
            schema_downgrades.append(
                f'    SchemaDowngrade("{action.schema_ref}", downgrade_{schema_name}),'
            )

        elif isinstance(action, SchemaDefinitionRemoved):
            # Removed schema - need upgrade to provide defaults
            schema_name = _schema_ref_to_name(action.schema_ref)

            # Extract field names for defaults
            old_schema = action.old_schema if isinstance(action.old_schema, dict) else {}
            props = old_schema.get("properties", {})
            field_names = list(props.keys()) if isinstance(props, dict) else []

            func_lines = [
                f"def upgrade_{schema_name}(data: dict) -> dict:",
                f'    """{from_version or "initial"} -> {to_version}: Provide defaults for removed schema."""',
                '    raise NotImplementedError("Schema was removed - provide migration for incoming requests")',
            ]
            if field_names:
                func_lines.append(f"    # Fields that existed: {', '.join(field_names)}")

            upgrade_functions.append("\n".join(func_lines))
            schema_upgrades.append(
                f'    SchemaUpgrade("{action.schema_ref}", upgrade_{schema_name}),'
            )

    # If no data migrations needed, return None
    if not downgrade_functions and not upgrade_functions and not path_rewrites:
        return None

    # Build the final code
    parts = []

    if downgrade_functions:
        parts.append("# Downgrade transformers (new -> old)")
        parts.extend(downgrade_functions)
        parts.append("")

    if upgrade_functions:
        parts.append("# Upgrade transformers (old -> new)")
        parts.extend(upgrade_functions)
        parts.append("")

    # Build DataMigrationSet
    parts.append("data_migrations = DataMigrationSet(")
    if schema_downgrades:
        parts.append("    schema_downgrades=[")
        parts.extend(schema_downgrades)
        parts.append("    ],")
    if schema_upgrades:
        parts.append("    schema_upgrades=[")
        parts.extend(schema_upgrades)
        parts.append("    ],")
    if path_rewrites:
        parts.append("    path_rewrites=[")
        parts.extend(path_rewrites)
        parts.append("    ],")
    parts.append(")")

    return "\n".join(parts)


def render_migration_file(
    dependencies: list[MigrationRef],
    from_version: str | None,
    to_version: str,
    description: str,
    delta: VersionDelta,
    data_migrations_code: str | None = None,
) -> str:
    """Generate Python source code for migration file."""
    delta_json = delta.model_dump_json(indent=4)

    from_desc = from_version or "empty"
    deps_repr = repr(dependencies)

    # Build imports
    imports = ["from crane.delta import VersionDelta"]
    if data_migrations_code:
        # Determine which data migration types are used
        dm_imports = ["DataMigrationSet"]
        if "SchemaDowngrade" in data_migrations_code:
            dm_imports.append("SchemaDowngrade")
        if "SchemaUpgrade" in data_migrations_code:
            dm_imports.append("SchemaUpgrade")
        if "PathRewrite" in data_migrations_code:
            dm_imports.append("PathRewrite")

        imports.append(
            "from crane.data_migrations import (\n    " + ",\n    ".join(dm_imports) + ",\n)"
        )

    imports_str = "\n".join(imports)

    # Build data migrations section
    data_migrations_section = ""
    if data_migrations_code:
        data_migrations_section = f"""

# === Data Migrations ===
# Transformers for converting data between API versions.
# Implement the NotImplementedError functions before deploying.

{data_migrations_code}
"""

    return f'''
"""
API migration: {from_desc} -> {to_version}

{description}
"""
{imports_str}

dependencies: list[tuple[str, str]] = {deps_repr}
from_version: str | None = {from_version!r}
to_version: str = {to_version!r}

delta = VersionDelta.model_validate_json("""
{delta_json}
""")
{data_migrations_section}'''


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

    # Generate data migration skeletons
    data_migrations_code = generate_data_migrations_code(delta, from_version, version_name)

    content = render_migration_file(
        dependencies, from_version, version_name, description, delta, data_migrations_code
    )

    migrations_path = _module_to_path(migrations_module)
    _ensure_migrations_package(migrations_path)

    file_path = migrations_path / filename
    file_path.write_text(content)

    return file_path
