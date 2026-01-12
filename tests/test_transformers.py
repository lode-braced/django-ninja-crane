"""Tests for runtime data transformers."""

from pathlib import Path

from crane.api_version import PathOperation
from crane.data_migrations import DataMigrationSet, OperationUpgrade, SchemaDowngrade, SchemaUpgrade
from crane.delta import HttpMethod, SchemaDefinitionAdded, VersionDelta
from crane.migrations_generator import LoadedMigration
from crane.transformers import (
    _get_migrations_between,
    get_latest_version,
    transform_request,
    transform_response,
    transform_response_list,
)


def make_migration(
    sequence: int,
    from_version: str | None,
    to_version: str,
    data_migrations: DataMigrationSet | None = None,
    delta: VersionDelta | None = None,
) -> LoadedMigration:
    """Helper to create test migrations."""
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


def make_operation(
    method: HttpMethod = "get",
    path: str = "/test",
    response_bodies: list[str] | None = None,
    request_body_schema: list[str] | None = None,
) -> PathOperation:
    """Helper to create test operations."""
    return PathOperation(
        method=method,
        path=path,
        query_params={},
        path_params={},
        cookie_params={},
        request_body_schema=request_body_schema or [],
        response_bodies=response_bodies or [],
        operation_id="test_op",
        openapi_json={},
    )


class TestGetMigrationsBetween:
    def test_same_version_returns_empty(self):
        migrations = [
            make_migration(1, None, "v1"),
            make_migration(2, "v1", "v2"),
        ]
        result = _get_migrations_between(migrations, "v1", "v1")
        assert result == []

    def test_downgrade_returns_reverse_order(self):
        migrations = [
            make_migration(1, None, "v1"),
            make_migration(2, "v1", "v2"),
            make_migration(3, "v2", "v3"),
        ]
        result = _get_migrations_between(migrations, "v3", "v1")
        # Should return v3, v2 (in reverse order, excluding v1)
        assert len(result) == 2
        assert result[0].to_version == "v3"
        assert result[1].to_version == "v2"

    def test_upgrade_returns_forward_order(self):
        migrations = [
            make_migration(1, None, "v1"),
            make_migration(2, "v1", "v2"),
            make_migration(3, "v2", "v3"),
        ]
        result = _get_migrations_between(migrations, "v1", "v3")
        # Should return v2, v3 (in forward order, excluding v1)
        assert len(result) == 2
        assert result[0].to_version == "v2"
        assert result[1].to_version == "v3"

    def test_unknown_version_returns_empty(self):
        migrations = [
            make_migration(1, None, "v1"),
        ]
        result = _get_migrations_between(migrations, "v1", "v99")
        assert result == []


class TestGetLatestVersion:
    def test_empty_migrations_returns_none(self):
        assert get_latest_version([]) is None

    def test_returns_last_migration_version(self):
        migrations = [
            make_migration(1, None, "v1"),
            make_migration(2, "v1", "v2"),
        ]
        assert get_latest_version(migrations) == "v2"


class TestTransformResponse:
    async def test_same_version_no_transform(self):
        data = {"name": "Alice", "is_active": True}
        operation = make_operation(response_bodies=["#/components/schemas/PersonOut"])
        migrations = [make_migration(1, None, "v1")]

        result = await transform_response(data, 200, operation, migrations, "v1", "v1")
        assert result == data

    async def test_applies_schema_downgrade(self):
        def downgrade_person(data: dict) -> dict:
            data.pop("is_active", None)
            return data

        data_migs = DataMigrationSet(
            schema_downgrades=[
                SchemaDowngrade("#/components/schemas/PersonOut", downgrade_person),
            ]
        )

        migrations = [
            make_migration(1, None, "v1"),
            make_migration(2, "v1", "v2", data_migs),
        ]

        operation = make_operation(response_bodies=["#/components/schemas/PersonOut"])
        data = {"name": "Alice", "is_active": True}

        result = await transform_response(data, 200, operation, migrations, "v2", "v1")

        assert result == {"name": "Alice"}
        assert "is_active" not in result

    async def test_applies_multiple_downgrades_in_order(self):
        def downgrade_v2(data: dict) -> dict:
            data.pop("field_v2", None)
            return data

        def downgrade_v3(data: dict) -> dict:
            data.pop("field_v3", None)
            return data

        migrations = [
            make_migration(1, None, "v1"),
            make_migration(
                2,
                "v1",
                "v2",
                DataMigrationSet(
                    schema_downgrades=[
                        SchemaDowngrade("#/components/schemas/Test", downgrade_v2),
                    ]
                ),
            ),
            make_migration(
                3,
                "v2",
                "v3",
                DataMigrationSet(
                    schema_downgrades=[
                        SchemaDowngrade("#/components/schemas/Test", downgrade_v3),
                    ]
                ),
            ),
        ]

        operation = make_operation(response_bodies=["#/components/schemas/Test"])
        data = {"name": "test", "field_v2": "v2", "field_v3": "v3"}

        # Downgrade from v3 to v1 should apply v3 downgrade first, then v2
        result = await transform_response(data, 200, operation, migrations, "v3", "v1")

        assert result == {"name": "test"}


class TestTransformResponseList:
    async def test_transforms_each_item(self):
        def downgrade_person(data: dict) -> dict:
            data.pop("is_active", None)
            return data

        data_migs = DataMigrationSet(
            schema_downgrades=[
                SchemaDowngrade("#/components/schemas/PersonOut", downgrade_person),
            ]
        )

        migrations = [
            make_migration(1, None, "v1"),
            make_migration(2, "v1", "v2", data_migs),
        ]

        operation = make_operation(response_bodies=["#/components/schemas/PersonOut"])
        data = [
            {"name": "Alice", "is_active": True},
            {"name": "Bob", "is_active": False},
        ]

        result = await transform_response_list(data, 200, operation, migrations, "v2", "v1")

        assert len(result) == 2
        assert result[0] == {"name": "Alice"}
        assert result[1] == {"name": "Bob"}


class TestTransformRequest:
    async def test_same_version_no_transform(self):
        body = {"name": "Alice"}
        params = {"limit": "10"}
        operation = make_operation(
            method="post", request_body_schema=["#/components/schemas/PersonIn"]
        )
        migrations = [make_migration(1, None, "v1")]

        new_body, new_params = await transform_request(
            body, params, operation, migrations, "v1", "v1"
        )

        assert new_body == body
        assert new_params == params

    async def test_applies_schema_upgrade(self):
        def upgrade_person(data: dict) -> dict:
            data.setdefault("is_active", True)
            return data

        data_migs = DataMigrationSet(
            schema_upgrades=[
                SchemaUpgrade("#/components/schemas/PersonIn", upgrade_person),
            ]
        )

        migrations = [
            make_migration(1, None, "v1"),
            make_migration(2, "v1", "v2", data_migs),
        ]

        operation = make_operation(
            method="post", request_body_schema=["#/components/schemas/PersonIn"]
        )
        body = {"name": "Alice"}

        new_body, _ = await transform_request(body, {}, operation, migrations, "v1", "v2")

        assert new_body == {"name": "Alice", "is_active": True}

    async def test_applies_multiple_upgrades_in_order(self):
        def upgrade_v2(data: dict) -> dict:
            data.setdefault("field_v2", "default_v2")
            return data

        def upgrade_v3(data: dict) -> dict:
            data.setdefault("field_v3", "default_v3")
            return data

        migrations = [
            make_migration(1, None, "v1"),
            make_migration(
                2,
                "v1",
                "v2",
                DataMigrationSet(
                    schema_upgrades=[
                        SchemaUpgrade("#/components/schemas/Test", upgrade_v2),
                    ]
                ),
            ),
            make_migration(
                3,
                "v2",
                "v3",
                DataMigrationSet(
                    schema_upgrades=[
                        SchemaUpgrade("#/components/schemas/Test", upgrade_v3),
                    ]
                ),
            ),
        ]

        operation = make_operation(method="post", request_body_schema=["#/components/schemas/Test"])
        body = {"name": "test"}

        # Upgrade from v1 to v3 should apply v2 upgrade first, then v3
        new_body, _ = await transform_request(body, {}, operation, migrations, "v1", "v3")

        assert new_body == {"name": "test", "field_v2": "default_v2", "field_v3": "default_v3"}

    async def test_none_body_skips_schema_upgrades(self):
        """When body is None, schema upgrades should be skipped."""

        def upgrade_person(data: dict) -> dict:
            data.setdefault("is_active", True)
            return data

        data_migs = DataMigrationSet(
            schema_upgrades=[
                SchemaUpgrade("#/components/schemas/PersonIn", upgrade_person),
            ]
        )

        migrations = [
            make_migration(1, None, "v1"),
            make_migration(2, "v1", "v2", data_migs),
        ]

        operation = make_operation(
            method="get", request_body_schema=["#/components/schemas/PersonIn"]
        )

        # Body is None (e.g., GET request with no JSON body)
        new_body, new_params = await transform_request(
            None, {"limit": "10"}, operation, migrations, "v1", "v2"
        )

        # Body should remain None, params unchanged
        assert new_body is None
        assert new_params == {"limit": "10"}

    async def test_none_body_still_calls_operation_upgrade(self):
        """Operation upgrades still receive None body and can transform params."""

        def upgrade_op(body: dict | None, params: dict) -> tuple[dict | None, dict]:
            # Transform query params even when no body
            if "old_param" in params:
                params["new_param"] = params.pop("old_param")
            return body, params

        data_migs = DataMigrationSet(
            operation_upgrades=[
                OperationUpgrade("/test", "get", upgrade_op),
            ]
        )

        migrations = [
            make_migration(1, None, "v1"),
            make_migration(2, "v1", "v2", data_migs),
        ]

        operation = make_operation(method="get", path="/test")

        new_body, new_params = await transform_request(
            None, {"old_param": "value"}, operation, migrations, "v1", "v2"
        )

        assert new_body is None
        assert new_params == {"new_param": "value"}


class TestOperationAtVersion:
    """Test that operations are correctly looked up at specific versions."""

    def test_operation_exists_at_version(self):
        """Operation added in v1 should exist at v1."""
        from crane.delta import OperationAdded
        from crane.middleware import _get_api_state_at_version

        op = make_operation(method="get", path="/users")
        migrations = [
            LoadedMigration(
                sequence=1,
                slug="initial",
                file_path=Path("m_0001_initial.py"),
                dependencies=[],
                from_version=None,
                to_version="v1",
                delta=VersionDelta(
                    actions=[OperationAdded(path="/users", method="get", new_operation=op)]
                ),
                data_migrations=None,
            ),
        ]

        state = _get_api_state_at_version(migrations, "v1")
        assert "/users" in state.path_operations
        assert len(state.path_operations["/users"]) == 1

    def test_operation_removed_not_at_later_version(self):
        """Operation removed in v2 should not exist at v2."""
        from crane.delta import OperationAdded, OperationRemoved
        from crane.middleware import _get_api_state_at_version

        op = make_operation(method="get", path="/legacy")
        migrations = [
            LoadedMigration(
                sequence=1,
                slug="initial",
                file_path=Path("m_0001_initial.py"),
                dependencies=[],
                from_version=None,
                to_version="v1",
                delta=VersionDelta(
                    actions=[OperationAdded(path="/legacy", method="get", new_operation=op)]
                ),
                data_migrations=None,
            ),
            LoadedMigration(
                sequence=2,
                slug="remove_legacy",
                file_path=Path("m_0002_remove_legacy.py"),
                dependencies=[],
                from_version="v1",
                to_version="v2",
                delta=VersionDelta(
                    actions=[OperationRemoved(path="/legacy", method="get", old_operation=op)]
                ),
                data_migrations=None,
            ),
        ]

        # At v1, operation exists
        state_v1 = _get_api_state_at_version(migrations, "v1")
        assert "/legacy" in state_v1.path_operations

        # At v2, operation is gone
        state_v2 = _get_api_state_at_version(migrations, "v2")
        assert "/legacy" not in state_v2.path_operations

    def test_operation_modified_at_version(self):
        """Operation modified in v2 should have new metadata at v2."""
        from crane.delta import OperationAdded, OperationModified
        from crane.middleware import _get_api_state_at_version

        op_v1 = make_operation(
            method="get", path="/users", response_bodies=["#/components/schemas/UserV1"]
        )

        migrations = [
            LoadedMigration(
                sequence=1,
                slug="initial",
                file_path=Path("m_0001_initial.py"),
                dependencies=[],
                from_version=None,
                to_version="v1",
                delta=VersionDelta(
                    actions=[OperationAdded(path="/users", method="get", new_operation=op_v1)]
                ),
                data_migrations=None,
            ),
            LoadedMigration(
                sequence=2,
                slug="update_users",
                file_path=Path("m_0002_update_users.py"),
                dependencies=[],
                from_version="v1",
                to_version="v2",
                delta=VersionDelta(
                    actions=[
                        OperationModified(
                            path="/users",
                            method="get",
                            old_openapi_json={},
                            new_openapi_json={},
                            old_params={},
                            new_params={},
                            old_body_refs=[],
                            new_body_refs=[],
                            old_response_refs=["#/components/schemas/UserV1"],
                            new_response_refs=["#/components/schemas/UserV2"],
                        )
                    ]
                ),
                data_migrations=None,
            ),
        ]

        # At v1, operation has v1 schema
        state_v1 = _get_api_state_at_version(migrations, "v1")
        assert state_v1.path_operations["/users"][0].response_bodies == [
            "#/components/schemas/UserV1"
        ]

        # At v2, operation has v2 schema
        state_v2 = _get_api_state_at_version(migrations, "v2")
        assert state_v2.path_operations["/users"][0].response_bodies == [
            "#/components/schemas/UserV2"
        ]


class TestRecursiveTransformation:
    """Test that nested schema transformations are applied recursively."""

    async def test_transforms_nested_schema(self):
        """Transformer for nested AddressOut should be applied to PersonOut.address."""

        def downgrade_address(data: dict) -> dict:
            # v2 -> v1: Remove zip_code added in v2
            data.pop("zip_code", None)
            return data

        data_migs = DataMigrationSet(
            schema_downgrades=[
                SchemaDowngrade("#/components/schemas/AddressOut", downgrade_address),
            ]
        )

        # Schemas need to be in the delta so get_known_api_state can build them
        v2_delta = VersionDelta(
            actions=[
                SchemaDefinitionAdded(
                    schema_ref="#/components/schemas/PersonOut",
                    new_schema={
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "address": {"$ref": "#/components/schemas/AddressOut"},
                        },
                    },
                ),
                SchemaDefinitionAdded(
                    schema_ref="#/components/schemas/AddressOut",
                    new_schema={
                        "type": "object",
                        "properties": {
                            "street": {"type": "string"},
                            "zip_code": {"type": "string"},
                        },
                    },
                ),
            ]
        )

        migrations = [
            make_migration(1, None, "v1"),
            make_migration(2, "v1", "v2", data_migs, delta=v2_delta),
        ]

        operation = make_operation(response_bodies=["#/components/schemas/PersonOut"])

        data = {
            "name": "Alice",
            "address": {"street": "123 Main St", "zip_code": "12345"},
        }

        result = await transform_response(data, 200, operation, migrations, "v2", "v1")

        # zip_code should be removed from nested address
        assert result == {
            "name": "Alice",
            "address": {"street": "123 Main St"},
        }

    async def test_transforms_array_of_nested_schemas(self):
        """Transformer should be applied to each item in an array of refs."""

        def downgrade_address(data: dict) -> dict:
            data.pop("zip_code", None)
            return data

        data_migs = DataMigrationSet(
            schema_downgrades=[
                SchemaDowngrade("#/components/schemas/AddressOut", downgrade_address),
            ]
        )

        v2_delta = VersionDelta(
            actions=[
                SchemaDefinitionAdded(
                    schema_ref="#/components/schemas/PersonOut",
                    new_schema={
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "addresses": {
                                "type": "array",
                                "items": {"$ref": "#/components/schemas/AddressOut"},
                            },
                        },
                    },
                ),
                SchemaDefinitionAdded(
                    schema_ref="#/components/schemas/AddressOut",
                    new_schema={
                        "type": "object",
                        "properties": {
                            "street": {"type": "string"},
                            "zip_code": {"type": "string"},
                        },
                    },
                ),
            ]
        )

        migrations = [
            make_migration(1, None, "v1"),
            make_migration(2, "v1", "v2", data_migs, delta=v2_delta),
        ]

        operation = make_operation(response_bodies=["#/components/schemas/PersonOut"])

        data = {
            "name": "Alice",
            "addresses": [
                {"street": "123 Main St", "zip_code": "12345"},
                {"street": "456 Oak Ave", "zip_code": "67890"},
            ],
        }

        result = await transform_response(data, 200, operation, migrations, "v2", "v1")

        assert result == {
            "name": "Alice",
            "addresses": [
                {"street": "123 Main St"},
                {"street": "456 Oak Ave"},
            ],
        }

    async def test_transforms_deeply_nested_schemas(self):
        """Transformation should work for deeply nested schemas."""

        def downgrade_city(data: dict) -> dict:
            data.pop("population", None)
            return data

        data_migs = DataMigrationSet(
            schema_downgrades=[
                SchemaDowngrade("#/components/schemas/City", downgrade_city),
            ]
        )

        v2_delta = VersionDelta(
            actions=[
                SchemaDefinitionAdded(
                    schema_ref="#/components/schemas/PersonOut",
                    new_schema={
                        "type": "object",
                        "properties": {
                            "address": {"$ref": "#/components/schemas/Address"},
                        },
                    },
                ),
                SchemaDefinitionAdded(
                    schema_ref="#/components/schemas/Address",
                    new_schema={
                        "type": "object",
                        "properties": {
                            "city": {"$ref": "#/components/schemas/City"},
                        },
                    },
                ),
                SchemaDefinitionAdded(
                    schema_ref="#/components/schemas/City",
                    new_schema={
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "population": {"type": "integer"},
                        },
                    },
                ),
            ]
        )

        migrations = [
            make_migration(1, None, "v1"),
            make_migration(2, "v1", "v2", data_migs, delta=v2_delta),
        ]

        operation = make_operation(response_bodies=["#/components/schemas/PersonOut"])

        data = {
            "address": {
                "city": {"name": "New York", "population": 8000000},
            },
        }

        result = await transform_response(data, 200, operation, migrations, "v2", "v1")

        assert result == {
            "address": {
                "city": {"name": "New York"},
            },
        }

    async def test_applies_both_parent_and_nested_transformers(self):
        """Both parent and nested schema transformers should be applied."""

        def downgrade_person(data: dict) -> dict:
            data.pop("is_active", None)
            return data

        def downgrade_address(data: dict) -> dict:
            data.pop("zip_code", None)
            return data

        data_migs = DataMigrationSet(
            schema_downgrades=[
                SchemaDowngrade("#/components/schemas/PersonOut", downgrade_person),
                SchemaDowngrade("#/components/schemas/AddressOut", downgrade_address),
            ]
        )

        v2_delta = VersionDelta(
            actions=[
                SchemaDefinitionAdded(
                    schema_ref="#/components/schemas/PersonOut",
                    new_schema={
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "is_active": {"type": "boolean"},
                            "address": {"$ref": "#/components/schemas/AddressOut"},
                        },
                    },
                ),
                SchemaDefinitionAdded(
                    schema_ref="#/components/schemas/AddressOut",
                    new_schema={
                        "type": "object",
                        "properties": {
                            "street": {"type": "string"},
                            "zip_code": {"type": "string"},
                        },
                    },
                ),
            ]
        )

        migrations = [
            make_migration(1, None, "v1"),
            make_migration(2, "v1", "v2", data_migs, delta=v2_delta),
        ]

        operation = make_operation(response_bodies=["#/components/schemas/PersonOut"])

        data = {
            "name": "Alice",
            "is_active": True,
            "address": {"street": "123 Main St", "zip_code": "12345"},
        }

        result = await transform_response(data, 200, operation, migrations, "v2", "v1")

        # Both is_active and zip_code should be removed
        assert result == {
            "name": "Alice",
            "address": {"street": "123 Main St"},
        }


class TestAsyncTransformers:
    async def test_async_schema_downgrade(self):
        async def async_downgrade(data: dict) -> dict:
            data.pop("async_field", None)
            return data

        data_migs = DataMigrationSet(
            schema_downgrades=[
                SchemaDowngrade("#/components/schemas/Test", async_downgrade),
            ]
        )

        migrations = [
            make_migration(1, None, "v1"),
            make_migration(2, "v1", "v2", data_migs),
        ]

        operation = make_operation(response_bodies=["#/components/schemas/Test"])
        data = {"name": "test", "async_field": "value"}

        result = await transform_response(data, 200, operation, migrations, "v2", "v1")

        assert result == {"name": "test"}

    async def test_async_schema_upgrade(self):
        async def async_upgrade(data: dict) -> dict:
            data.setdefault("async_field", "default")
            return data

        data_migs = DataMigrationSet(
            schema_upgrades=[
                SchemaUpgrade("#/components/schemas/Test", async_upgrade),
            ]
        )

        migrations = [
            make_migration(1, None, "v1"),
            make_migration(2, "v1", "v2", data_migs),
        ]

        operation = make_operation(method="post", request_body_schema=["#/components/schemas/Test"])
        body = {"name": "test"}

        new_body, _ = await transform_request(body, {}, operation, migrations, "v1", "v2")

        assert new_body == {"name": "test", "async_field": "default"}
