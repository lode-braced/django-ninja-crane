"""Shared pytest fixtures for integration tests."""

from __future__ import annotations

import sys
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from crane.api_version import ApiVersion, PathOperation
from crane.data_migrations import DataMigrationSet, PathRewrite
from crane.delta import HttpMethod, VersionDelta
from crane.migrations_generator import LoadedMigration


@pytest.fixture
def temp_migrations_module(tmp_path: Path) -> Generator[tuple[str, Path], None, None]:
    """Create a temporary Python package for migrations.

    Yields:
        Tuple of (module_name, package_path) for the temporary migrations package.

    The fixture handles sys.path and sys.modules cleanup automatically.
    """
    pkg_name = "test_api_migrations"
    pkg_path = tmp_path / pkg_name
    pkg_path.mkdir()
    (pkg_path / "__init__.py").write_text("")

    # Add to sys.path for import
    sys.path.insert(0, str(tmp_path))

    yield pkg_name, pkg_path

    # Cleanup: remove from sys.path
    if str(tmp_path) in sys.path:
        sys.path.remove(str(tmp_path))

    # Cleanup: remove imported modules to avoid cross-test pollution
    modules_to_remove = [key for key in sys.modules if key.startswith(pkg_name)]
    for mod in modules_to_remove:
        del sys.modules[mod]


@pytest.fixture
def migration_factory():
    """Factory for creating LoadedMigration instances for testing."""

    def _make_migration(
        sequence: int,
        from_version: str | None,
        to_version: str,
        data_migrations: DataMigrationSet | None = None,
        delta: VersionDelta | None = None,
        path_rewrites: list[PathRewrite] | None = None,
    ) -> LoadedMigration:
        # If path_rewrites provided without data_migrations, create DataMigrationSet
        if path_rewrites and not data_migrations:
            data_migrations = DataMigrationSet(path_rewrites=path_rewrites)

        return LoadedMigration(
            sequence=sequence,
            slug=f"m{sequence}",
            file_path=Path(f"m_{sequence:04d}_m{sequence}.py"),
            dependencies=[],
            from_version=from_version,
            to_version=to_version,
            delta=delta or VersionDelta(actions=[]),
            data_migrations=data_migrations,
        )

    return _make_migration


@pytest.fixture
def operation_factory():
    """Factory for creating PathOperation instances for testing."""

    def _make_operation(
        method: HttpMethod = "get",
        path: str = "/test",
        operation_id: str = "test_op",
        query_params: dict[str, Any] | None = None,
        path_params: dict[str, Any] | None = None,
        cookie_params: dict[str, Any] | None = None,
        request_body_schema: list[str] | None = None,
        response_bodies: list[str] | None = None,
        openapi_json: dict[str, Any] | None = None,
    ) -> PathOperation:
        return PathOperation(
            method=method,
            path=path,
            query_params=query_params or {},
            path_params=path_params or {},
            cookie_params=cookie_params or {},
            request_body_schema=request_body_schema or [],
            response_bodies=response_bodies or [],
            operation_id=operation_id,
            openapi_json=openapi_json or {"operationId": operation_id},
        )

    return _make_operation


@pytest.fixture
def api_version_factory(operation_factory):
    """Factory for creating ApiVersion instances for testing."""

    def _make_api_version(
        operations: list[PathOperation] | None = None,
        schemas: dict[str, Any] | None = None,
    ) -> ApiVersion:
        path_ops: dict[str, list[PathOperation]] = {}
        for op in operations or []:
            if op.path not in path_ops:
                path_ops[op.path] = []
            path_ops[op.path].append(op)
        return ApiVersion(
            path_operations=path_ops,
            schema_definitions=schemas or {},
        )

    return _make_api_version


@pytest.fixture
def reset_versioned_api_registry():
    """Fixture that clears the VersionedNinjaAPI registry before and after tests.

    Use this fixture for tests that create VersionedNinjaAPI instances to prevent
    test pollution from leftover registered APIs.
    """
    from crane.versioned_api import VersionedNinjaAPI

    VersionedNinjaAPI.clear_registry()
    yield VersionedNinjaAPI
    VersionedNinjaAPI.clear_registry()
