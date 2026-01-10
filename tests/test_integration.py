"""Integration tests for django-ninja-crane.

These tests verify end-to-end workflows:
1. Define NinjaAPI within test modules
2. Generate migrations from API changes
3. Test runtime transformation
4. Simulate multiple API versions
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from ninja import NinjaAPI, Router, Schema

from crane.api_version import ApiVersion, PathOperation
from crane.data_migrations import DataMigrationSet, PathRewrite, SchemaDowngrade, SchemaUpgrade
from crane.delta import SchemaDefinitionAdded, SchemaDefinitionModified, VersionDelta
from crane.migrations_generator import LoadedMigration, generate_migration, load_migrations
from crane.transformers import transform_request, transform_response


@dataclass
class EvolvedAPISetup:
    """Typed container for the evolved_api_setup fixture."""

    api_v1: NinjaAPI
    api_v2: NinjaAPI
    v1_state: ApiVersion
    v2_state: ApiVersion
    delta: VersionDelta
    migrations: list[LoadedMigration]


def make_migration(
    sequence: int,
    from_version: str | None,
    to_version: str,
    data_migrations: DataMigrationSet | None = None,
    delta: VersionDelta | None = None,
) -> LoadedMigration:
    """Helper to create test migrations without file I/O."""
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


def make_v1_schema_delta(schema_ref: str, properties: dict) -> VersionDelta:
    """Helper to create a v1 delta that adds a schema."""
    return VersionDelta(
        actions=[
            SchemaDefinitionAdded(
                schema_ref=schema_ref,
                new_schema={"type": "object", "properties": properties},
            ),
        ]
    )


class TestSchemaEvolutionIntegration:
    """End-to-end tests for schema evolution scenarios."""

    async def test_add_optional_field_downgrade(self):
        """v1 has PersonOut(name); v2 adds is_active field; v1 clients don't see it."""

        def downgrade_person(data: dict) -> dict:
            data.pop("is_active", None)
            return data

        # v1 introduces PersonOut with just 'name'
        v1_delta = make_v1_schema_delta(
            "#/components/schemas/PersonOut",
            {"name": {"type": "string"}},
        )

        # v2 modifies PersonOut to add 'is_active'
        v2_delta = VersionDelta(
            actions=[
                SchemaDefinitionModified(
                    schema_ref="#/components/schemas/PersonOut",
                    old_schema={"properties": {"name": {"type": "string"}}},
                    new_schema={
                        "properties": {
                            "name": {"type": "string"},
                            "is_active": {"type": "boolean", "default": True},
                        }
                    },
                ),
            ]
        )

        data_migs = DataMigrationSet(
            schema_downgrades=[
                SchemaDowngrade("#/components/schemas/PersonOut", downgrade_person),
            ]
        )

        migrations = [
            make_migration(1, None, "v1", delta=v1_delta),
            make_migration(2, "v1", "v2", data_migs, v2_delta),
        ]

        operation = PathOperation(
            method="get",
            path="/persons/{person_id}",
            query_params={},
            path_params={},
            cookie_params={},
            request_body_schema=[],
            response_bodies=["#/components/schemas/PersonOut"],
            operation_id="get_person",
            openapi_json={},
        )

        response_data = {"name": "Alice", "is_active": True}
        result = await transform_response(response_data, 200, operation, migrations, "v2", "v1")

        # v1 client should not see is_active
        assert result == {"name": "Alice"}
        assert "is_active" not in result

    async def test_remove_field_downgrade(self):
        """v1 has ItemOut(name, legacy_field); v2 removes legacy_field; v1 clients still see it."""

        def downgrade_item(data: dict) -> dict:
            data["legacy_field"] = "restored_default"
            return data

        # v1 introduces ItemOut with 'name' and 'legacy_field'
        v1_delta = make_v1_schema_delta(
            "#/components/schemas/ItemOut",
            {"name": {"type": "string"}, "legacy_field": {"type": "string"}},
        )

        # v2 modifies ItemOut to remove 'legacy_field'
        v2_delta = VersionDelta(
            actions=[
                SchemaDefinitionModified(
                    schema_ref="#/components/schemas/ItemOut",
                    old_schema={
                        "properties": {
                            "name": {"type": "string"},
                            "legacy_field": {"type": "string"},
                        }
                    },
                    new_schema={"properties": {"name": {"type": "string"}}},
                ),
            ]
        )

        data_migs = DataMigrationSet(
            schema_downgrades=[
                SchemaDowngrade("#/components/schemas/ItemOut", downgrade_item),
            ]
        )

        migrations = [
            make_migration(1, None, "v1", delta=v1_delta),
            make_migration(2, "v1", "v2", data_migs, v2_delta),
        ]

        operation = PathOperation(
            method="get",
            path="/items/{item_id}",
            query_params={},
            path_params={},
            cookie_params={},
            request_body_schema=[],
            response_bodies=["#/components/schemas/ItemOut"],
            operation_id="get_item",
            openapi_json={},
        )

        response_data = {"name": "Widget"}
        result = await transform_response(response_data, 200, operation, migrations, "v2", "v1")

        # v1 client should see legacy_field restored
        assert result == {"name": "Widget", "legacy_field": "restored_default"}

    async def test_nested_schema_transformation(self):
        """v1 has Address(street); v2 adds zip_code; transformation removes it for v1."""

        def downgrade_address(data: dict) -> dict:
            data.pop("zip_code", None)
            return data

        # v1 introduces PersonOut with Address(street only)
        v1_delta = VersionDelta(
            actions=[
                SchemaDefinitionAdded(
                    schema_ref="#/components/schemas/PersonOut",
                    new_schema={
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "address": {"$ref": "#/components/schemas/Address"},
                        },
                    },
                ),
                SchemaDefinitionAdded(
                    schema_ref="#/components/schemas/Address",
                    new_schema={
                        "type": "object",
                        "properties": {"street": {"type": "string"}},
                    },
                ),
            ]
        )

        # v2 modifies Address to add zip_code
        v2_delta = VersionDelta(
            actions=[
                SchemaDefinitionModified(
                    schema_ref="#/components/schemas/Address",
                    old_schema={"properties": {"street": {"type": "string"}}},
                    new_schema={
                        "properties": {
                            "street": {"type": "string"},
                            "zip_code": {"type": "string"},
                        }
                    },
                ),
            ]
        )

        data_migs = DataMigrationSet(
            schema_downgrades=[
                SchemaDowngrade("#/components/schemas/Address", downgrade_address),
            ]
        )

        migrations = [
            make_migration(1, None, "v1", delta=v1_delta),
            make_migration(2, "v1", "v2", data_migs, v2_delta),
        ]

        operation = PathOperation(
            method="get",
            path="/persons/{person_id}",
            query_params={},
            path_params={},
            cookie_params={},
            request_body_schema=[],
            response_bodies=["#/components/schemas/PersonOut"],
            operation_id="get_person",
            openapi_json={},
        )

        response_data = {
            "name": "Alice",
            "address": {"street": "123 Main St", "zip_code": "12345"},
        }
        result = await transform_response(response_data, 200, operation, migrations, "v2", "v1")

        # zip_code should be removed from nested address
        assert result == {"name": "Alice", "address": {"street": "123 Main St"}}


class TestRequestTransformationIntegration:
    """End-to-end tests for request body transformation."""

    async def test_request_body_upgrade(self):
        """v1 has PersonIn(name); v2 adds is_active; v1 request gets upgraded."""

        def upgrade_person_in(data: dict) -> dict:
            data.setdefault("is_active", True)
            return data

        # v1 introduces PersonIn with just 'name'
        v1_delta = make_v1_schema_delta(
            "#/components/schemas/PersonIn",
            {"name": {"type": "string"}},
        )

        # v2 modifies PersonIn to add 'is_active'
        v2_delta = VersionDelta(
            actions=[
                SchemaDefinitionModified(
                    schema_ref="#/components/schemas/PersonIn",
                    old_schema={"properties": {"name": {"type": "string"}}},
                    new_schema={
                        "properties": {
                            "name": {"type": "string"},
                            "is_active": {"type": "boolean", "default": True},
                        }
                    },
                ),
            ]
        )

        data_migs = DataMigrationSet(
            schema_upgrades=[
                SchemaUpgrade("#/components/schemas/PersonIn", upgrade_person_in),
            ]
        )

        migrations = [
            make_migration(1, None, "v1", delta=v1_delta),
            make_migration(2, "v1", "v2", data_migs, v2_delta),
        ]

        operation = PathOperation(
            method="post",
            path="/persons",
            query_params={},
            path_params={},
            cookie_params={},
            request_body_schema=["#/components/schemas/PersonIn"],
            response_bodies=[],
            operation_id="create_person",
            openapi_json={},
        )

        # v1 client sends body without is_active
        request_body = {"name": "Alice"}
        new_body, new_params = await transform_request(
            request_body, {}, operation, migrations, "v1", "v2"
        )

        # v2 endpoint should receive is_active=True
        assert new_body == {"name": "Alice", "is_active": True}


class TestMultiVersionIntegration:
    """End-to-end tests for multi-version migration chains."""

    async def test_three_version_chain(self):
        """v3 response downgrades through v2 to v1.

        Uses operation-level downgrades since each migration has its own context.
        """

        # Define operation-level downgrades that work at each migration step
        def downgrade_v3_to_v2(data: dict, status_code: int) -> dict:
            data.pop("stock", None)
            return data

        def downgrade_v2_to_v1(data: dict, status_code: int) -> dict:
            data.pop("price", None)
            return data

        from crane.data_migrations import OperationDowngrade

        migrations = [
            make_migration(1, None, "v1"),
            make_migration(
                2,
                "v1",
                "v2",
                DataMigrationSet(
                    operation_downgrades=[
                        OperationDowngrade("/items/{item_id}", "get", downgrade_v2_to_v1),
                    ]
                ),
            ),
            make_migration(
                3,
                "v2",
                "v3",
                DataMigrationSet(
                    operation_downgrades=[
                        OperationDowngrade("/items/{item_id}", "get", downgrade_v3_to_v2),
                    ]
                ),
            ),
        ]

        operation = PathOperation(
            method="get",
            path="/items/{item_id}",
            query_params={},
            path_params={},
            cookie_params={},
            request_body_schema=[],
            response_bodies=["#/components/schemas/ItemOut"],
            operation_id="get_item",
            openapi_json={},
        )

        # v3 response
        response_data = {"name": "Widget", "price": 9.99, "stock": 100}

        # Downgrade v3 → v2 (removes stock)
        result_v2 = await transform_response(
            response_data.copy(), 200, operation, migrations, "v3", "v2"
        )
        assert result_v2 == {"name": "Widget", "price": 9.99}

        # Downgrade v3 → v1 (removes stock and price)
        result_v1 = await transform_response(
            response_data.copy(), 200, operation, migrations, "v3", "v1"
        )
        assert result_v1 == {"name": "Widget"}


class TestPathRewriteIntegration:
    """End-to-end tests for path rewriting."""

    async def test_path_rename_with_transformation(self, tmp_path: Path):
        """Path rename from /persons to /people with data transformation."""

        # === Define v1 API ===
        class PersonOutV1(Schema):
            name: str

        api_v1 = NinjaAPI()
        router_v1 = Router()

        @router_v1.get("/persons/{person_id}")
        def get_person_v1(request, person_id: int) -> PersonOutV1:
            return {"name": "Alice"}

        api_v1.add_router("", router_v1)

        migrations_dir = tmp_path / "path_rename"
        migrations_dir.mkdir()
        (migrations_dir / "__init__.py").write_text("")

        sys.path.insert(0, str(tmp_path))
        try:
            m1 = generate_migration(api_v1, "path_rename", "v1", "Initial API")
            assert m1 is not None

            # === Define v2 API with renamed path and new field ===
            class PersonOutV2(Schema):
                name: str
                is_active: bool = True

            api_v2 = NinjaAPI()
            router_v2 = Router()

            @router_v2.get("/people/{person_id}")
            def get_person_v2(request, person_id: int) -> PersonOutV2:
                return {"name": "Alice", "is_active": True}

            api_v2.add_router("", router_v2)

            m2 = generate_migration(api_v2, "path_rename", "v2", "Rename path and add field")
            assert m2 is not None

            # Add data migration with path rewrite
            def downgrade_person(data: dict) -> dict:
                data.pop("is_active", None)
                return data

            data_migs = DataMigrationSet(
                schema_downgrades=[
                    SchemaDowngrade("#/components/schemas/PersonOutV2", downgrade_person),
                ],
                path_rewrites=[
                    PathRewrite(
                        old_path="/persons/{person_id}",
                        new_path="/people/{person_id}",
                    ),
                ],
            )

            migrations = load_migrations("path_rename")
            migrations[1].data_migrations = data_migs

            # Test path rewriting
            from crane.path_rewriting import get_path_rewrites_for_upgrade, rewrite_path

            rewrites = get_path_rewrites_for_upgrade(migrations, "v1", "v2")
            assert len(rewrites) == 1

            new_path = rewrite_path("/persons/123", "get", rewrites)
            assert new_path == "/people/123"

            # Test data transformation
            operation = PathOperation(
                method="get",
                path="/people/{person_id}",
                query_params={},
                path_params={},
                cookie_params={},
                request_body_schema=[],
                response_bodies=["#/components/schemas/PersonOutV2"],
                operation_id="get_person_v2",
                openapi_json={},
            )

            response_data = {"name": "Alice", "is_active": True}
            result = await transform_response(response_data, 200, operation, migrations, "v2", "v1")
            assert result == {"name": "Alice"}

        finally:
            sys.path.remove(str(tmp_path))
            for key in list(sys.modules.keys()):
                if key.startswith("path_rename"):
                    del sys.modules[key]


class TestMiddlewareIntegration:
    """Integration tests for the middleware with Django test client."""

    def test_middleware_version_extraction(self, settings):
        """Verify middleware extracts version from header."""
        from django.test import RequestFactory

        from crane.middleware import VersionedAPIMiddleware

        # Create a mock get_response
        def mock_get_response(request):
            from django.http import JsonResponse

            return JsonResponse({"version": getattr(request, "api_version", "unknown")})

        middleware = VersionedAPIMiddleware(mock_get_response)

        # Override settings for this test
        settings.CRANE_SETTINGS = {
            "version_header": "X-API-Version",
            "version_query_param": "api_version",
            "default_version": "latest",
            "migrations_module": "",  # No migrations for this test
            "api_url_prefix": "/api/",
        }

        # Reinitialize middleware with new settings
        middleware = VersionedAPIMiddleware(mock_get_response)

        factory = RequestFactory()

        # Request with version header
        request = factory.get("/api/test", HTTP_X_API_VERSION="v1")
        extracted = middleware._extract_version(request)
        assert extracted == "v1"

        # Request with query param
        request = factory.get("/api/test?api_version=v2")
        extracted = middleware._extract_version(request)
        assert extracted == "v2"

        # Request with no version (uses default)
        request = factory.get("/api/test")
        extracted = middleware._extract_version(request)
        assert extracted == "latest"

    def test_middleware_unknown_version_error(self, tmp_path: Path, settings):
        """Middleware returns 400 for unknown versions."""
        from django.http import JsonResponse
        from django.test import RequestFactory

        from crane.middleware import VersionedAPIMiddleware

        # Setup migrations
        migrations_dir = tmp_path / "mw_unknown"
        migrations_dir.mkdir()
        (migrations_dir / "__init__.py").write_text("")

        # Create a simple v1 migration
        class ItemOut(Schema):
            name: str

        api = NinjaAPI()
        router = Router()

        @router.get("/items")
        def list_items(request) -> list[ItemOut]:
            return []

        api.add_router("", router)

        sys.path.insert(0, str(tmp_path))
        try:
            generate_migration(api, "mw_unknown", "v1", "Initial")

            settings.CRANE_SETTINGS = {
                "version_header": "X-API-Version",
                "version_query_param": "api_version",
                "default_version": "latest",
                "migrations_module": "mw_unknown",
                "api_url_prefix": "/api/",
            }

            def mock_get_response(request):
                return JsonResponse({"status": "ok"})

            middleware = VersionedAPIMiddleware(mock_get_response)

            factory = RequestFactory()
            request = factory.get("/api/items", HTTP_X_API_VERSION="v99")
            response = middleware(request)

            assert response.status_code == 400
            assert b"Unknown API version" in response.content

        finally:
            sys.path.remove(str(tmp_path))
            for key in list(sys.modules.keys()):
                if key.startswith("mw_unknown"):
                    del sys.modules[key]

    def test_middleware_passthrough_for_latest(self, tmp_path: Path, settings):
        """Middleware passes through unchanged for latest version."""
        from django.http import JsonResponse
        from django.test import RequestFactory

        from crane.middleware import VersionedAPIMiddleware

        migrations_dir = tmp_path / "mw_latest"
        migrations_dir.mkdir()
        (migrations_dir / "__init__.py").write_text("")

        class ItemOut(Schema):
            name: str

        api = NinjaAPI()
        router = Router()

        @router.get("/items")
        def list_items(request) -> list[ItemOut]:
            return []

        api.add_router("", router)

        sys.path.insert(0, str(tmp_path))
        try:
            generate_migration(api, "mw_latest", "v1", "Initial")

            settings.CRANE_SETTINGS = {
                "version_header": "X-API-Version",
                "version_query_param": "api_version",
                "default_version": "latest",
                "migrations_module": "mw_latest",
                "api_url_prefix": "/api/",
            }

            response_data = {"items": [{"name": "Widget"}]}

            def mock_get_response(request):
                return JsonResponse(response_data)

            middleware = VersionedAPIMiddleware(mock_get_response)

            factory = RequestFactory()

            # Request for latest (v1 is latest)
            request = factory.get("/api/items", HTTP_X_API_VERSION="v1")
            response = middleware(request)

            assert response.status_code == 200
            # No transformation for latest version
            import json

            assert json.loads(response.content) == response_data

        finally:
            sys.path.remove(str(tmp_path))
            for key in list(sys.modules.keys()):
                if key.startswith("mw_latest"):
                    del sys.modules[key]


# =============================================================================
# High-Level Integration Tests: Full API Definition → Delta → Transformation
# =============================================================================

# Module-level schemas for Pydantic reference resolution
# V1 schemas


class AddressV1(Schema):
    street: str


class PersonOutV1(Schema):
    id: int
    name: str
    address: AddressV1


class PersonInV1(Schema):
    name: str


class ItemOutV1(Schema):
    name: str


# V2 schemas (evolved from V1)


class AddressV2(Schema):
    street: str
    city: str = "Unknown"


class PersonOutV2(Schema):
    id: int
    name: str
    is_active: bool = True
    address: AddressV2


class PersonInV2(Schema):
    name: str
    email: str = "unknown@example.com"


class ItemOutV2(Schema):
    name: str
    price: float = 0.0


@pytest.fixture
def evolved_api_setup() -> EvolvedAPISetup:
    """
    Shared fixture that creates v1 and v2 NinjaAPI instances with multiple endpoints,
    computes deltas, and builds migrations with data transformers.

    This represents a realistic API evolution scenario:
    - PersonOut: adds is_active field, nested Address adds city
    - PersonIn: adds email field
    - ItemOut: adds price field
    - Multiple endpoints share schemas
    """
    from crane.api_version import create_api_version
    from crane.delta import create_delta

    # === V1 API ===
    api_v1 = NinjaAPI(title="Test API v1")

    @api_v1.get("/persons", response=list[PersonOutV1])
    def list_persons_v1(request):
        return []

    @api_v1.get("/persons/{person_id}", response=PersonOutV1)
    def get_person_v1(request, person_id: int):
        return {"id": person_id, "name": "Alice", "address": {"street": "123 Main St"}}

    @api_v1.post("/persons", response=PersonOutV1)
    def create_person_v1(request, payload: PersonInV1):
        return {"id": 1, "name": payload.name, "address": {"street": "Unknown"}}

    @api_v1.get("/items", response=list[ItemOutV1])
    def list_items_v1(request):
        return []

    @api_v1.get("/items/{item_id}", response=ItemOutV1)
    def get_item_v1(request, item_id: int):
        return {"name": "Widget"}

    @api_v1.get("/featured", response=ItemOutV1)
    def get_featured_v1(request):
        return {"name": "Featured Widget"}

    # === V2 API ===
    api_v2 = NinjaAPI(title="Test API v2")

    @api_v2.get("/persons", response=list[PersonOutV2])
    def list_persons_v2(request):
        return []

    @api_v2.get("/persons/{person_id}", response=PersonOutV2)
    def get_person_v2(request, person_id: int):
        return {
            "id": person_id,
            "name": "Alice",
            "is_active": True,
            "address": {"street": "123 Main St", "city": "NYC"},
        }

    @api_v2.post("/persons", response=PersonOutV2)
    def create_person_v2(request, payload: PersonInV2):
        return {
            "id": 1,
            "name": payload.name,
            "is_active": True,
            "address": {"street": "Unknown", "city": "Unknown"},
        }

    @api_v2.get("/items", response=list[ItemOutV2])
    def list_items_v2(request):
        return []

    @api_v2.get("/items/{item_id}", response=ItemOutV2)
    def get_item_v2(request, item_id: int):
        return {"name": "Widget", "price": 9.99}

    @api_v2.get("/featured", response=ItemOutV2)
    def get_featured_v2(request):
        return {"name": "Featured Widget", "price": 19.99}

    # === Extract API states ===
    v1_state = create_api_version(api_v1)
    v2_state = create_api_version(api_v2)
    delta = create_delta(v1_state, v2_state)

    # === Data transformers ===
    def downgrade_person_out(data: dict) -> dict:
        data.pop("is_active", None)
        return data

    def downgrade_address(data: dict) -> dict:
        data.pop("city", None)
        return data

    def upgrade_person_in(data: dict) -> dict:
        data.setdefault("email", "unknown@example.com")
        return data

    def downgrade_item_out(data: dict) -> dict:
        data.pop("price", None)
        return data

    # === Build migrations ===
    v1_migration = LoadedMigration(
        sequence=1,
        slug="initial",
        file_path=Path("m_0001_initial.py"),
        dependencies=[],
        from_version=None,
        to_version="v1",
        delta=create_delta(ApiVersion(path_operations={}, schema_definitions={}), v1_state),
        data_migrations=None,
    )

    v2_migration = LoadedMigration(
        sequence=2,
        slug="v2_evolution",
        file_path=Path("m_0002_v2_evolution.py"),
        dependencies=[],
        from_version="v1",
        to_version="v2",
        delta=delta,
        data_migrations=DataMigrationSet(
            schema_downgrades=[
                SchemaDowngrade("#/components/schemas/PersonOutV2", downgrade_person_out),
                SchemaDowngrade("#/components/schemas/AddressV2", downgrade_address),
                SchemaDowngrade("#/components/schemas/ItemOutV2", downgrade_item_out),
            ],
            schema_upgrades=[
                SchemaUpgrade("#/components/schemas/PersonInV2", upgrade_person_in),
            ],
        ),
    )

    migrations = [v1_migration, v2_migration]

    return EvolvedAPISetup(
        api_v1=api_v1,
        api_v2=api_v2,
        v1_state=v1_state,
        v2_state=v2_state,
        delta=delta,
        migrations=migrations,
    )


class TestFullAPIEvolutionIntegration:
    """
    High-level integration tests using a shared API evolution fixture.

    All tests share the same v1 → v2 API evolution setup and test different aspects.
    """

    async def test_response_field_addition_stripped_for_v1(
        self, evolved_api_setup: EvolvedAPISetup
    ):
        """v2 PersonOut has is_active; v1 clients don't see it."""
        operation = evolved_api_setup.v2_state.path_operations["/persons/{person_id}"][0]
        response_data = {
            "id": 1,
            "name": "Alice",
            "is_active": True,
            "address": {"street": "123 Main St", "city": "NYC"},
        }

        result = await transform_response(
            response_data, 200, operation, evolved_api_setup.migrations, "v2", "v1"
        )

        assert "is_active" not in result
        assert result["name"] == "Alice"

    async def test_nested_schema_field_stripped_for_v1(self, evolved_api_setup: EvolvedAPISetup):
        """v2 Address has city; v1 clients don't see it in nested address."""
        operation = evolved_api_setup.v2_state.path_operations["/persons/{person_id}"][0]
        response_data = {
            "id": 1,
            "name": "Alice",
            "is_active": True,
            "address": {"street": "123 Main St", "city": "NYC"},
        }

        result = await transform_response(
            response_data, 200, operation, evolved_api_setup.migrations, "v2", "v1"
        )

        assert "city" not in result["address"]
        assert result["address"]["street"] == "123 Main St"

    async def test_request_body_upgraded_with_default(self, evolved_api_setup: EvolvedAPISetup):
        """v1 PersonIn lacks email; v2 endpoint receives default."""
        # Find the POST operation (not GET)
        operations = evolved_api_setup.v2_state.path_operations["/persons"]
        operation = next(op for op in operations if op.method == "post")
        request_body = {"name": "Alice"}

        new_body, _ = await transform_request(
            request_body, {}, operation, evolved_api_setup.migrations, "v1", "v2"
        )

        assert new_body["email"] == "unknown@example.com"
        assert new_body["name"] == "Alice"

    async def test_item_price_stripped_for_v1(self, evolved_api_setup: EvolvedAPISetup):
        """v2 ItemOut has price; v1 clients don't see it."""
        operation = evolved_api_setup.v2_state.path_operations["/items/{item_id}"][0]
        response_data = {"name": "Widget", "price": 9.99}

        result = await transform_response(
            response_data, 200, operation, evolved_api_setup.migrations, "v2", "v1"
        )

        assert result == {"name": "Widget"}
        assert "price" not in result

    async def test_same_schema_transformed_across_endpoints(
        self, evolved_api_setup: EvolvedAPISetup
    ):
        """ItemOut transformation applies to both /items/{id} and /featured."""
        v2_state = evolved_api_setup.v2_state
        migrations = evolved_api_setup.migrations

        # Test /items/{item_id}
        item_op = v2_state.path_operations["/items/{item_id}"][0]
        result = await transform_response(
            {"name": "Widget", "price": 9.99}, 200, item_op, migrations, "v2", "v1"
        )
        assert result == {"name": "Widget"}

        # Test /featured (same schema, different endpoint)
        featured_op = v2_state.path_operations["/featured"][0]
        result = await transform_response(
            {"name": "Featured", "price": 19.99}, 200, featured_op, migrations, "v2", "v1"
        )
        assert result == {"name": "Featured"}

    async def test_v2_to_v2_passthrough(self, evolved_api_setup: EvolvedAPISetup):
        """v2 request to v2 endpoint passes through unchanged."""
        operation = evolved_api_setup.v2_state.path_operations["/persons/{person_id}"][0]
        response_data = {
            "id": 1,
            "name": "Alice",
            "is_active": True,
            "address": {"street": "123 Main St", "city": "NYC"},
        }

        result = await transform_response(
            response_data, 200, operation, evolved_api_setup.migrations, "v2", "v2"
        )

        # No transformation for same version
        assert result == response_data

    async def test_delta_contains_expected_changes(self, evolved_api_setup: EvolvedAPISetup):
        """Verify the computed delta captures schema modifications."""
        delta = evolved_api_setup.delta

        # Should have multiple actions for schema changes
        assert len(delta.actions) > 0

        # Check that we have schema-related actions
        action_types = {type(a).__name__ for a in delta.actions}
        # Expect removed v1 schemas and added v2 schemas
        assert "SchemaDefinitionRemoved" in action_types or "SchemaDefinitionAdded" in action_types

    async def test_api_states_have_expected_schemas(self, evolved_api_setup: EvolvedAPISetup):
        """Verify API states extracted correct schemas."""
        v1_state = evolved_api_setup.v1_state
        v2_state = evolved_api_setup.v2_state

        # v1 should have v1 schemas
        v1_schema_names = list(v1_state.schema_definitions.keys())
        assert any("PersonOutV1" in name for name in v1_schema_names)
        assert any("AddressV1" in name for name in v1_schema_names)
        assert any("ItemOutV1" in name for name in v1_schema_names)

        # v2 should have v2 schemas
        v2_schema_names = list(v2_state.schema_definitions.keys())
        assert any("PersonOutV2" in name for name in v2_schema_names)
        assert any("AddressV2" in name for name in v2_schema_names)
        assert any("ItemOutV2" in name for name in v2_schema_names)
