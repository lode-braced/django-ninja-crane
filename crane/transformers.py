"""Runtime data transformation for API versioning.

This module provides functions to transform request/response data between API versions
by applying the data migrations defined in migration files.

Note on schema transformers:
- Schema transformers are applied recursively to nested data structures
- If a schema has properties that reference other schemas, those nested schemas
  will have their transformers applied first (depth-first)
- When an operation has multiple response body schemas (union types), transformers
  for ALL matching schemas are applied. Transformer authors should handle this by
  checking if their fields exist before modifying.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any, cast
from asgiref.sync import sync_to_async

from crane.api_version import AnyJson, PathOperation
from crane.data_migrations import DataMigrationSet
from crane.migrations_generator import LoadedMigration, get_known_api_state

type GetTransformer = Callable[[str], Any | None]

logger = logging.getLogger(__name__)


async def _call_transformer(
    transformer: Any,
    *args: Any,
) -> Any:
    """Call a transformer, handling both sync and async functions."""
    if asyncio.iscoroutinefunction(transformer):
        return await transformer(*args)
    else:
        return sync_to_async(transformer)(*args)


def _extract_refs_from_schema(schema: AnyJson) -> list[str]:
    """Extract all $ref strings from a schema, handling nested structures."""
    if not isinstance(schema, dict):
        return []

    refs: list[str] = []

    # Direct $ref
    ref = schema.get("$ref")
    if isinstance(ref, str):
        refs.append(ref)

    # Array items
    if "items" in schema:
        refs.extend(_extract_refs_from_schema(schema["items"]))

    # anyOf / oneOf / allOf
    for key in ("anyOf", "oneOf", "allOf"):
        variants = schema.get(key)
        if isinstance(variants, list):
            for variant in variants:
                refs.extend(_extract_refs_from_schema(variant))

    # additionalProperties
    if "additionalProperties" in schema and isinstance(schema["additionalProperties"], dict):
        refs.extend(_extract_refs_from_schema(schema["additionalProperties"]))

    return refs


def _resolve_schema_ref(ref: str, schema_definitions: dict[str, AnyJson]) -> AnyJson | None:
    """Resolve a $ref like '#/components/schemas/PersonOut' to its schema."""
    # Handle standard OpenAPI ref format
    if ref.startswith("#/components/schemas/"):
        # Try full ref first
        if ref in schema_definitions:
            return schema_definitions[ref]

        # Fall back to just the schema name
        schema_name = ref.split("/")[-1]
        if schema_name in schema_definitions:
            logger.debug(
                "Schema ref %r not found, but found by short name %r. "
                "Consider using full refs in schema_definitions.",
                ref,
                schema_name,
            )
            return schema_definitions[schema_name]

        return None

    return schema_definitions.get(ref)


async def _transform_data_recursive(
    data: Any,
    schema: AnyJson,
    schema_definitions: dict[str, AnyJson],
    get_transformer: GetTransformer,
) -> Any:
    """Recursively transform data according to schema structure.

    Applies transformers depth-first: nested schemas are transformed before their parents.
    """
    if data is None or not isinstance(schema, dict):
        return data

    # Handle $ref - resolve and transform
    if "$ref" in schema:
        ref: str = cast(str, schema["$ref"])
        resolved_schema = _resolve_schema_ref(ref, schema_definitions)

        # First transform nested properties (depth-first)
        if isinstance(data, dict) and resolved_schema:
            data = await _transform_object_properties(
                data, resolved_schema, schema_definitions, get_transformer
            )

        # Then apply this schema's transformer
        transformer = get_transformer(ref)
        if transformer and isinstance(data, dict):
            data = await _call_transformer(transformer, data)

        return data

    # Handle array - transform each item
    if schema.get("type") == "array" and "items" in schema:
        if isinstance(data, list):
            return [
                await _transform_data_recursive(
                    item, schema["items"], schema_definitions, get_transformer
                )
                for item in data
            ]
        return data

    # Handle anyOf/oneOf - try to match and transform
    for key in ("anyOf", "oneOf"):
        if key in schema and isinstance(schema[key], list):
            # Apply transformers for all variants that have refs
            # (transformer should handle checking if fields exist)
            for variant in cast(list[AnyJson], schema[key]):
                data = await _transform_data_recursive(
                    data, variant, schema_definitions, get_transformer
                )
            return data

    # Handle object with properties
    if isinstance(data, dict) and "properties" in schema:
        data = await _transform_object_properties(data, schema, schema_definitions, get_transformer)

    return data


async def _transform_object_properties(
    data: dict[str, Any],
    schema: AnyJson,
    schema_definitions: dict[str, AnyJson],
    get_transformer: GetTransformer,
) -> dict[str, Any]:
    """Transform each property of an object according to its schema."""
    if not isinstance(schema, dict):
        return data

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return data

    result = dict(data)

    for prop_name, prop_schema in properties.items():
        if prop_name in result and isinstance(prop_schema, dict):
            result[prop_name] = await _transform_data_recursive(
                result[prop_name], prop_schema, schema_definitions, get_transformer
            )

    return result


def _get_migrations_between(
    migrations: list[LoadedMigration],
    from_version: str,
    to_version: str,
) -> list[LoadedMigration]:
    """Get migrations between two versions (exclusive of from, inclusive of to).

    For downgrade (from_version > to_version in sequence):
        Returns migrations in reverse order (newest first)

    For upgrade (from_version < to_version in sequence):
        Returns migrations in forward order (oldest first)
    """
    # Build version to index mapping
    version_to_idx = {m.to_version: i for i, m in enumerate(migrations)}

    if from_version not in version_to_idx or to_version not in version_to_idx:
        # One of the versions doesn't exist
        return []

    from_idx = version_to_idx[from_version]
    to_idx = version_to_idx[to_version]

    if from_idx == to_idx:
        return []

    if from_idx > to_idx:
        # Downgrade: return migrations from from_idx down to to_idx+1 (reverse order)
        return list(reversed(migrations[to_idx + 1 : from_idx + 1]))
    else:
        # Upgrade: return migrations from from_idx+1 up to to_idx (forward order)
        return migrations[from_idx + 1 : to_idx + 1]


def _get_schema_definitions_at_version(
    migrations: list[LoadedMigration],
    version: str,
) -> dict[str, AnyJson]:
    """Get schema definitions at a specific version by applying migrations up to that point."""
    version_to_idx = {m.to_version: i for i, m in enumerate(migrations)}

    if version not in version_to_idx:
        return {}

    idx = version_to_idx[version]
    api_state = get_known_api_state(migrations[: idx + 1])
    return api_state.schema_definitions


async def transform_response(
    response_data: dict[str, Any],
    status_code: int,
    operation: PathOperation,
    migrations: list[LoadedMigration],
    from_version: str,
    to_version: str,
) -> dict[str, Any]:
    """Transform response data from current version to an older version (downgrade).

    Args:
        response_data: The response data to transform.
        status_code: HTTP status code of the response.
        operation: The PathOperation metadata for this endpoint.
        migrations: All loaded migrations.
        from_version: The current API version (newer).
        to_version: The target API version (older).

    Returns:
        Transformed response data suitable for the older API version.
    """
    if from_version == to_version:
        return response_data

    # Get migrations to apply (in reverse order for downgrade)
    migs_to_apply = _get_migrations_between(migrations, from_version, to_version)

    if not migs_to_apply:
        return response_data

    data = response_data

    for migration in migs_to_apply:
        data_migs = migration.data_migrations
        if data_migs is None:
            continue

        # Check for operation-level downgrade first
        op_downgrade = data_migs.get_operation_downgrade(operation.path, operation.method)
        if op_downgrade:
            data = await _call_transformer(op_downgrade.transformer, data, status_code)
            continue

        # Get schema definitions at the version BEFORE this downgrade
        # (data is in migration.to_version format before we transform it)
        schema_definitions = _get_schema_definitions_at_version(migrations, migration.to_version)

        # Build a getter function for this migration's transformers
        def get_downgrade(ref: str, dm: DataMigrationSet = data_migs) -> Any | None:
            downgrade = dm.get_schema_downgrade(ref)
            return downgrade.transformer if downgrade else None

        # Transform each response body schema (handles union types)
        for schema_ref in operation.response_bodies:
            schema = {"$ref": schema_ref}
            data = await _transform_data_recursive(data, schema, schema_definitions, get_downgrade)

    return data


async def transform_response_list(
    response_data: list[dict[str, Any]],
    status_code: int,
    operation: PathOperation,
    migrations: list[LoadedMigration],
    from_version: str,
    to_version: str,
) -> list[dict[str, Any]]:
    """Transform a list of response items (e.g., for list endpoints)."""
    return [
        await transform_response(item, status_code, operation, migrations, from_version, to_version)
        for item in response_data
    ]


async def transform_request(
    body: dict[str, Any] | None,
    query_params: dict[str, Any],
    operation: PathOperation,
    migrations: list[LoadedMigration],
    from_version: str,
    to_version: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Transform request data from an older version to current version (upgrade).

    Args:
        body: The request body to transform, or None for non-JSON requests.
        query_params: Query parameters to transform.
        operation: The PathOperation metadata for this endpoint.
        migrations: All loaded migrations.
        from_version: The source API version (older).
        to_version: The target API version (current/newer).

    Returns:
        Tuple of (transformed_body, transformed_query_params).
        Body will be None if input body was None.
    """
    if from_version == to_version:
        return body, query_params

    # Get migrations to apply (in forward order for upgrade)
    migs_to_apply = _get_migrations_between(migrations, from_version, to_version)

    if not migs_to_apply:
        return body, query_params

    current_body = body
    current_params = query_params

    for migration in migs_to_apply:
        data_migs = migration.data_migrations
        if data_migs is None:
            continue

        # Check for operation-level upgrade first (receives body which may be None)
        op_upgrade = data_migs.get_operation_upgrade(operation.path, operation.method)
        if op_upgrade:
            current_body, current_params = await _call_transformer(
                op_upgrade.transformer, current_body, current_params
            )
            continue

        # Apply schema-level upgrades only if we have a body
        if current_body is not None:
            # Get schema definitions at the version BEFORE this upgrade
            # (data is in migration.from_version format before we transform it)
            schema_definitions: dict[str, AnyJson] = {}
            if migration.from_version:
                schema_definitions = _get_schema_definitions_at_version(
                    migrations, migration.from_version
                )

            # Build a getter function for this migration's transformers
            def get_upgrade(ref: str, dm: DataMigrationSet = data_migs) -> Any | None:
                upgrade = dm.get_schema_upgrade(ref)
                return upgrade.transformer if upgrade else None

            for schema_ref in operation.request_body_schema:
                schema = {"$ref": schema_ref}
                current_body = await _transform_data_recursive(
                    current_body, schema, schema_definitions, get_upgrade
                )

    return current_body, current_params


def get_latest_version(migrations: list[LoadedMigration]) -> str | None:
    """Get the latest version from migrations."""
    if not migrations:
        return None
    return migrations[-1].to_version
