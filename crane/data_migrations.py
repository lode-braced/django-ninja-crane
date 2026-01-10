"""Data migration models for transforming request/response data between API versions.

This module provides:
- SchemaDowngrade/SchemaUpgrade: Transform data for a specific schema wherever it appears
- OperationDowngrade/OperationUpgrade: Transform data for a specific endpoint
- ParamTransform: Transform query/path parameters
- DataMigrationSet: Container for all data migrations in a migration file
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from crane.delta import HttpMethod

# Type aliases for transformer functions
# Schema transformers operate on the data dict for a schema instance
type SchemaTransformer = Callable[[dict[str, Any]], dict[str, Any]]
type AsyncSchemaTransformer = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

# Operation transformers have full control over request/response
# RequestTransformer receives (body, query_params) and returns (new_body, new_params)
type RequestTransformer = Callable[
    [dict[str, Any], dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]
]
type AsyncRequestTransformer = Callable[
    [dict[str, Any], dict[str, Any]], Awaitable[tuple[dict[str, Any], dict[str, Any]]]
]
# ResponseTransformer receives (response_data, status_code) and returns new data
type ResponseTransformer = Callable[[dict[str, Any], int], dict[str, Any]]
type AsyncResponseTransformer = Callable[[dict[str, Any], int], Awaitable[dict[str, Any]]]


@dataclass
class SchemaDowngrade:
    """Transform response data when downgrading to an older API version.

    Applied automatically wherever this schema appears in responses:
    - Direct response body
    - Nested within other schemas
    - Items in arrays

    Example:
        def downgrade_person_out(data: dict) -> dict:
            # v2 -> v1: Remove is_active field added in v2
            data.pop("is_active", None)
            return data

        SchemaDowngrade(
            schema_ref="#/components/schemas/PersonOut",
            transformer=downgrade_person_out,
        )
    """

    schema_ref: str
    transformer: SchemaTransformer | AsyncSchemaTransformer


@dataclass
class SchemaUpgrade:
    """Transform request data when upgrading from an older API version.

    Applied automatically wherever this schema appears in request bodies:
    - Direct request body
    - Nested within other schemas
    - Items in arrays

    Example:
        def upgrade_person_in(data: dict) -> dict:
            # v1 -> v2: Add is_active with default value
            data.setdefault("is_active", True)
            return data

        SchemaUpgrade(
            schema_ref="#/components/schemas/PersonIn",
            transformer=upgrade_person_in,
        )
    """

    schema_ref: str
    transformer: SchemaTransformer | AsyncSchemaTransformer


@dataclass
class OperationDowngrade:
    """Transform response for a specific endpoint when downgrading.

    Use this when schema-level transformations aren't sufficient,
    such as when the endpoint needs custom logic based on the full response.

    The transformer receives (response_data, status_code) and returns modified data.

    Example:
        def downgrade_list_users(data: dict, status_code: int) -> dict:
            # Custom logic for list users endpoint
            if "items" in data:
                for item in data["items"]:
                    item.pop("internal_id", None)
            return data

        OperationDowngrade(
            path="/api/users",
            method="get",
            transformer=downgrade_list_users,
        )
    """

    path: str
    method: HttpMethod
    transformer: ResponseTransformer | AsyncResponseTransformer


@dataclass
class OperationUpgrade:
    """Transform request for a specific endpoint when upgrading.

    Use this when schema-level transformations aren't sufficient,
    such as when you need to transform both body and params together.

    The transformer receives (body, query_params) and returns (new_body, new_params).

    Example:
        def upgrade_create_user(body: dict, params: dict) -> tuple[dict, dict]:
            # Move 'role' from query param to body in v2
            if "role" in params:
                body["role"] = params.pop("role")
            return body, params

        OperationUpgrade(
            path="/api/users",
            method="post",
            transformer=upgrade_create_user,
        )
    """

    path: str
    method: HttpMethod
    transformer: RequestTransformer | AsyncRequestTransformer


@dataclass
class PathRewrite:
    """Map an old path to a new path when an endpoint is renamed.

    Used when an endpoint's URL path changes between versions. The middleware
    rewrites incoming requests from old paths to new paths before Django's
    URL resolution, allowing old clients to continue using old URLs.

    Path parameters use {name} syntax and are preserved during rewriting.

    Example - in v1->v2 migration where /persons/{id} became /people/{id}:
        PathRewrite(
            old_path="/persons/{person_id}",
            new_path="/people/{person_id}",
        )

    Example - parameter rename:
        PathRewrite(
            old_path="/users/{user_id}",
            new_path="/users/{id}",  # param renamed
        )
    """

    old_path: str  # Path pattern at the old version
    new_path: str  # Path pattern at the new version
    methods: list[HttpMethod] | None = None  # None means all methods


@dataclass
class DataMigrationSet:
    """Container for all data migrations in a single migration file.

    Organizes schema-level and operation-level transformers for both
    upgrade (old -> new) and downgrade (new -> old) directions.

    Example:
        data_migrations = DataMigrationSet(
            schema_downgrades=[
                SchemaDowngrade("#/components/schemas/PersonOut", downgrade_person),
            ],
            schema_upgrades=[
                SchemaUpgrade("#/components/schemas/PersonIn", upgrade_person),
            ],
        )
    """

    # Schema-level transformations (applied wherever schema appears)
    schema_downgrades: list[SchemaDowngrade] = field(default_factory=list)
    schema_upgrades: list[SchemaUpgrade] = field(default_factory=list)

    # Operation-level transformations (full control over specific endpoints)
    # Use these for endpoint-specific logic or when schema-level isn't sufficient
    # OperationUpgrade receives (body, query_params) so it can transform params too
    operation_downgrades: list[OperationDowngrade] = field(default_factory=list)
    operation_upgrades: list[OperationUpgrade] = field(default_factory=list)

    # Path rewrites for URL changes between versions
    # Applied by middleware before Django's URL resolution
    path_rewrites: list[PathRewrite] = field(default_factory=list)

    def is_empty(self) -> bool:
        """Return True if no data migrations are defined."""
        return not any(
            [
                self.schema_downgrades,
                self.schema_upgrades,
                self.operation_downgrades,
                self.operation_upgrades,
                self.path_rewrites,
            ]
        )

    def get_schema_downgrade(self, schema_ref: str) -> SchemaDowngrade | None:
        """Get the downgrade transformer for a specific schema."""
        for downgrade in self.schema_downgrades:
            if downgrade.schema_ref == schema_ref:
                return downgrade
        return None

    def get_schema_upgrade(self, schema_ref: str) -> SchemaUpgrade | None:
        """Get the upgrade transformer for a specific schema."""
        for upgrade in self.schema_upgrades:
            if upgrade.schema_ref == schema_ref:
                return upgrade
        return None

    def get_operation_downgrade(self, path: str, method: HttpMethod) -> OperationDowngrade | None:
        """Get the downgrade transformer for a specific operation."""
        for downgrade in self.operation_downgrades:
            if downgrade.path == path and downgrade.method == method:
                return downgrade
        return None

    def get_operation_upgrade(self, path: str, method: HttpMethod) -> OperationUpgrade | None:
        """Get the upgrade transformer for a specific operation."""
        for upgrade in self.operation_upgrades:
            if upgrade.path == path and upgrade.method == method:
                return upgrade
        return None
