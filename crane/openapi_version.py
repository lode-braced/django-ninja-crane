"""Generate versioned OpenAPI schemas by applying backwards deltas.

This module provides functionality to transform the current OpenAPI schema to
any previous API version by applying migration deltas in reverse.
"""

from __future__ import annotations

from typing import cast

from ninja import NinjaAPI

from crane.api_version import AnyJsonDict, ApiVersion, create_api_version
from crane.delta import apply_delta_backwards
from crane.migrations_generator import load_migrations, LoadedMigration


class VersionNotFoundError(Exception):
    """Target version not found in migrations."""


def _ref_to_schema_name(ref: str) -> str:
    """Convert '#/components/schemas/Person' to 'Person'."""
    return ref.rsplit("/", 1)[-1]


def api_version_to_openapi(
    api_version: ApiVersion,
    base_openapi: AnyJsonDict,
    path_prefix: str = "",
) -> AnyJsonDict:
    """Convert an ApiVersion to a complete OpenAPI JSON document.

    Args:
        api_version: The API version to convert.
        base_openapi: Base OpenAPI structure (info, servers, security, etc.)
                      Paths and components/schemas will be replaced.
        path_prefix: URL prefix to prepend to all paths (e.g., "/api").

    Returns:
        Complete OpenAPI JSON document.
    """
    result = dict(base_openapi)

    # Normalize prefix (ensure it doesn't end with slash)
    prefix = path_prefix.rstrip("/") if path_prefix else ""

    # Build paths from path_operations
    paths: AnyJsonDict = {}
    for path, operations in api_version.path_operations.items():
        path_item: AnyJsonDict = {}
        for op in operations:
            path_item[op.method] = op.openapi_json
        # Add prefix to path
        full_path = prefix + path if prefix else path
        paths[full_path] = path_item

    result["paths"] = paths

    # Build components/schemas from schema_definitions
    schemas: AnyJsonDict = {}
    for ref, schema in api_version.schema_definitions.items():
        schema_name = _ref_to_schema_name(ref)
        schemas[schema_name] = schema

    # Preserve existing components, just replace schemas
    components = dict(cast(AnyJsonDict, result.get("components", {})))
    components["schemas"] = schemas
    result["components"] = components

    return result


def get_versioned_openapi(
    api: NinjaAPI,
    migrations_module: str,
    target_version: str,
) -> AnyJsonDict:
    """Get the OpenAPI schema for a specific API version.

    Applies backwards deltas from the current API state to the target version.

    Args:
        api: The current NinjaAPI instance.
        migrations_module: Module path to migrations.
        target_version: The target version name (must exist in migrations).

    Returns:
        OpenAPI JSON document for the target version.

    Raises:
        VersionNotFoundError: If target version is not found in migrations.
    """
    migrations = load_migrations(migrations_module)

    if not migrations:
        raise VersionNotFoundError(
            f"No migrations found in {migrations_module}. Cannot resolve version '{target_version}'."
        )

    # Find the target version in migrations
    target_index = _find_version_index(migrations, target_version)
    if target_index is None:
        available = [m.to_version for m in migrations]
        raise VersionNotFoundError(
            f"Version '{target_version}' not found in migrations. Available versions: {available}"
        )

    # Get current API state and OpenAPI schema (with path prefix)
    current_state = create_api_version(api)
    path_prefix = api.get_root_path({})
    current_openapi = cast(AnyJsonDict, api.get_openapi_schema(path_prefix=path_prefix))

    # Apply backwards deltas from most recent to target (exclusive)
    # We need to reverse migrations from index (len-1) down to (target_index+1)
    state = current_state
    for i in range(len(migrations) - 1, target_index, -1):
        state = apply_delta_backwards(state, migrations[i].delta)

    # Convert the resulting state to OpenAPI format (with path prefix)
    return api_version_to_openapi(state, current_openapi, path_prefix)


def _find_version_index(migrations: list[LoadedMigration], version: str) -> int | None:
    """Find the index of a version in the migrations list."""
    for i, m in enumerate(migrations):
        if m.to_version == version:
            return i
    return None


def get_available_versions(migrations_module: str) -> list[str]:
    """Get list of available API versions from migrations.

    Args:
        migrations_module: Module path to migrations.

    Returns:
        List of version names in chronological order.
    """
    migrations = load_migrations(migrations_module)
    return [m.to_version for m in migrations]
