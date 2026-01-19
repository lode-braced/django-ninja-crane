import sys
from textwrap import dedent

import pytest
from ninja import NinjaAPI

from crane.openapi_version import (
    VersionNotFoundError,
    api_version_to_openapi,
    get_available_versions,
    get_versioned_openapi,
)
from crane.api_version import ApiVersion, PathOperation


class TestApiVersionToOpenapi:
    def test_empty_api_version(self):
        api_version = ApiVersion(path_operations={}, schema_definitions={})
        base_openapi = {
            "openapi": "3.1.0",
            "info": {"title": "Test API", "version": "1.0.0"},
        }

        result = api_version_to_openapi(api_version, base_openapi)

        assert result["openapi"] == "3.1.0"
        assert result["info"]["title"] == "Test API"
        assert result["paths"] == {}
        assert result["components"]["schemas"] == {}

    def test_single_operation(self):
        op = PathOperation(
            method="get",
            path="/users",
            query_params={},
            path_params={},
            cookie_params={},
            request_body_schema=[],
            response_bodies=[],
            operation_id="list_users",
            openapi_json={
                "operationId": "list_users",
                "summary": "List all users",
                "responses": {"200": {"description": "Success"}},
            },
        )
        api_version = ApiVersion(
            path_operations={"/users": [op]},
            schema_definitions={},
        )
        base_openapi = {"openapi": "3.1.0", "info": {"title": "Test", "version": "1.0"}}

        result = api_version_to_openapi(api_version, base_openapi)

        assert "/users" in result["paths"]
        assert "get" in result["paths"]["/users"]
        assert result["paths"]["/users"]["get"]["operationId"] == "list_users"

    def test_multiple_methods_on_path(self):
        get_op = PathOperation(
            method="get",
            path="/items",
            query_params={},
            path_params={},
            cookie_params={},
            request_body_schema=[],
            response_bodies=[],
            operation_id="list_items",
            openapi_json={"operationId": "list_items"},
        )
        post_op = PathOperation(
            method="post",
            path="/items",
            query_params={},
            path_params={},
            cookie_params={},
            request_body_schema=[],
            response_bodies=[],
            operation_id="create_item",
            openapi_json={"operationId": "create_item"},
        )
        api_version = ApiVersion(
            path_operations={"/items": [get_op, post_op]},
            schema_definitions={},
        )
        base_openapi = {"openapi": "3.1.0", "info": {"title": "Test", "version": "1.0"}}

        result = api_version_to_openapi(api_version, base_openapi)

        assert "get" in result["paths"]["/items"]
        assert "post" in result["paths"]["/items"]

    def test_schema_definitions_converted(self):
        api_version = ApiVersion(
            path_operations={},
            schema_definitions={
                "#/components/schemas/User": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
                "#/components/schemas/Item": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}},
                },
            },
        )
        base_openapi = {"openapi": "3.1.0", "info": {"title": "Test", "version": "1.0"}}

        result = api_version_to_openapi(api_version, base_openapi)

        assert "User" in result["components"]["schemas"]
        assert "Item" in result["components"]["schemas"]
        assert result["components"]["schemas"]["User"]["properties"]["name"]["type"] == "string"

    def test_preserves_other_components(self):
        api_version = ApiVersion(path_operations={}, schema_definitions={})
        base_openapi = {
            "openapi": "3.1.0",
            "info": {"title": "Test", "version": "1.0"},
            "components": {
                "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}},
                "schemas": {"OldSchema": {"type": "object"}},
            },
        }

        result = api_version_to_openapi(api_version, base_openapi)

        # securitySchemes preserved, schemas replaced
        assert "bearerAuth" in result["components"]["securitySchemes"]
        assert result["components"]["schemas"] == {}


class TestGetVersionedOpenapi:
    def test_version_not_found_raises_error(self, tmp_path):
        api = NinjaAPI()

        @api.get("/test")
        def test_endpoint():
            return {}

        migrations_dir = tmp_path / "test_version_missing"
        migrations_dir.mkdir()
        (migrations_dir / "__init__.py").write_text("")

        # Create one migration
        content = dedent("""
            from crane.delta import VersionDelta
            dependencies = []
            from_version = None
            to_version = "v1"
            delta = VersionDelta(actions=[])
        """)
        (migrations_dir / "m_0001_v1.py").write_text(content)

        sys.path.insert(0, str(tmp_path))
        try:
            with pytest.raises(VersionNotFoundError, match="v99.*not found"):
                get_versioned_openapi(api, "test_version_missing", "v99")
        finally:
            sys.path.remove(str(tmp_path))
            for key in list(sys.modules.keys()):
                if key.startswith("test_version_missing"):
                    del sys.modules[key]

    def test_no_migrations_raises_error(self):
        api = NinjaAPI()

        @api.get("/test")
        def test_endpoint():
            return {}

        with pytest.raises(VersionNotFoundError, match="No migrations found"):
            get_versioned_openapi(api, "nonexistent.module", "v1")

    def test_returns_current_state_for_latest_version(self, tmp_path):
        api = NinjaAPI()

        @api.get("/users")
        def list_users():
            return []

        migrations_dir = tmp_path / "test_latest_version"
        migrations_dir.mkdir()
        (migrations_dir / "__init__.py").write_text("")

        # Create migration with the current endpoint
        content = dedent("""
            from crane.delta import VersionDelta, OperationAdded
            from crane.api_version import PathOperation

            dependencies = []
            from_version = None
            to_version = "v1"

            op = PathOperation(
                method="get",
                path="/users",
                query_params={},
                path_params={},
                cookie_params={},
                request_body_schema=[],
                response_bodies=[],
                operation_id="list_users",
                openapi_json={"operationId": "list_users"},
            )
            delta = VersionDelta(actions=[
                OperationAdded(path="/users", method="get", new_operation=op)
            ])
        """)
        (migrations_dir / "m_0001_v1.py").write_text(content)

        sys.path.insert(0, str(tmp_path))
        try:
            result = get_versioned_openapi(api, "test_latest_version", "v1")

            # Paths include the API prefix (e.g., /api/users)
            assert "/api/users" in result["paths"]
            assert "get" in result["paths"]["/api/users"]
        finally:
            sys.path.remove(str(tmp_path))
            for key in list(sys.modules.keys()):
                if key.startswith("test_latest_version"):
                    del sys.modules[key]

    def test_applies_backwards_delta(self, tmp_path):
        """Test that requesting an older version removes newer endpoints."""
        api = NinjaAPI()

        @api.get("/users")
        def list_users():
            return []

        @api.get("/items")
        def list_items():
            return []

        migrations_dir = tmp_path / "test_backwards"
        migrations_dir.mkdir()
        (migrations_dir / "__init__.py").write_text("")

        # First migration: adds /users
        m1 = dedent("""
            from crane.delta import VersionDelta, OperationAdded
            from crane.api_version import PathOperation

            dependencies = []
            from_version = None
            to_version = "v1"

            op = PathOperation(
                method="get",
                path="/users",
                query_params={},
                path_params={},
                cookie_params={},
                request_body_schema=[],
                response_bodies=[],
                operation_id="list_users",
                openapi_json={"operationId": "list_users"},
            )
            delta = VersionDelta(actions=[
                OperationAdded(path="/users", method="get", new_operation=op)
            ])
        """)
        (migrations_dir / "m_0001_v1.py").write_text(m1)

        # Second migration: adds /items
        m2 = dedent("""
            from crane.delta import VersionDelta, OperationAdded
            from crane.api_version import PathOperation

            dependencies = [("test_backwards", "v1")]
            from_version = "v1"
            to_version = "v2"

            op = PathOperation(
                method="get",
                path="/items",
                query_params={},
                path_params={},
                cookie_params={},
                request_body_schema=[],
                response_bodies=[],
                operation_id="list_items",
                openapi_json={"operationId": "list_items"},
            )
            delta = VersionDelta(actions=[
                OperationAdded(path="/items", method="get", new_operation=op)
            ])
        """)
        (migrations_dir / "m_0002_v2.py").write_text(m2)

        sys.path.insert(0, str(tmp_path))
        try:
            # Request v1 (should not have /items)
            result_v1 = get_versioned_openapi(api, "test_backwards", "v1")

            # Paths include the API prefix (e.g., /api/users)
            assert "/api/users" in result_v1["paths"]
            assert "/api/items" not in result_v1["paths"]

            # Request v2 (should have both)
            result_v2 = get_versioned_openapi(api, "test_backwards", "v2")

            assert "/api/users" in result_v2["paths"]
            assert "/api/items" in result_v2["paths"]
        finally:
            sys.path.remove(str(tmp_path))
            for key in list(sys.modules.keys()):
                if key.startswith("test_backwards"):
                    del sys.modules[key]


class TestGetAvailableVersions:
    def test_no_migrations_returns_empty(self):
        result = get_available_versions("nonexistent.module")
        assert result == []

    def test_returns_versions_in_order(self, tmp_path):
        migrations_dir = tmp_path / "test_available"
        migrations_dir.mkdir()
        (migrations_dir / "__init__.py").write_text("")

        for seq, version in [(1, "initial"), (2, "add_users"), (3, "add_items")]:
            content = dedent(f"""
                from crane.delta import VersionDelta
                dependencies = []
                from_version = None
                to_version = "{version}"
                delta = VersionDelta(actions=[])
            """)
            (migrations_dir / f"m_{seq:04d}_{version}.py").write_text(content)

        sys.path.insert(0, str(tmp_path))
        try:
            result = get_available_versions("test_available")
            assert result == ["initial", "add_users", "add_items"]
        finally:
            sys.path.remove(str(tmp_path))
            for key in list(sys.modules.keys()):
                if key.startswith("test_available"):
                    del sys.modules[key]
