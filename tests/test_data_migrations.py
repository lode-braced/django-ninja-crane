"""Tests for data_migrations module."""

from crane.data_migrations import (
    DataMigrationSet,
    OperationDowngrade,
    OperationUpgrade,
    SchemaDowngrade,
    SchemaUpgrade,
)


class TestSchemaDowngrade:
    def test_creates_with_schema_ref_and_transformer(self):
        def transformer(data: dict) -> dict:
            data.pop("field", None)
            return data

        downgrade = SchemaDowngrade(
            schema_ref="#/components/schemas/PersonOut",
            transformer=transformer,
        )

        assert downgrade.schema_ref == "#/components/schemas/PersonOut"
        assert downgrade.transformer is transformer

    def test_transformer_can_modify_data(self):
        def transformer(data: dict) -> dict:
            data.pop("is_active", None)
            return data

        downgrade = SchemaDowngrade(
            schema_ref="#/components/schemas/PersonOut",
            transformer=transformer,
        )

        result = downgrade.transformer({"name": "Alice", "is_active": True})
        assert result == {"name": "Alice"}


class TestSchemaUpgrade:
    def test_creates_with_schema_ref_and_transformer(self):
        def transformer(data: dict) -> dict:
            data.setdefault("is_active", True)
            return data

        upgrade = SchemaUpgrade(
            schema_ref="#/components/schemas/PersonIn",
            transformer=transformer,
        )

        assert upgrade.schema_ref == "#/components/schemas/PersonIn"
        assert upgrade.transformer is transformer

    def test_transformer_can_add_defaults(self):
        def transformer(data: dict) -> dict:
            data.setdefault("is_active", True)
            return data

        upgrade = SchemaUpgrade(
            schema_ref="#/components/schemas/PersonIn",
            transformer=transformer,
        )

        result = upgrade.transformer({"name": "Alice"})
        assert result == {"name": "Alice", "is_active": True}


class TestOperationDowngrade:
    def test_creates_with_path_method_and_transformer(self):
        def transformer(data: dict, status_code: int) -> dict:
            return data

        downgrade = OperationDowngrade(
            path="/api/users",
            method="get",
            transformer=transformer,
        )

        assert downgrade.path == "/api/users"
        assert downgrade.method == "get"
        assert downgrade.transformer is transformer

    def test_transformer_receives_status_code(self):
        def transformer(data: dict, status_code: int) -> dict:
            if status_code == 200:
                data["status"] = "ok"
            return data

        downgrade = OperationDowngrade(
            path="/api/users",
            method="get",
            transformer=transformer,
        )

        result = downgrade.transformer({"items": []}, 200)
        assert result == {"items": [], "status": "ok"}


class TestOperationUpgrade:
    def test_creates_with_path_method_and_transformer(self):
        def transformer(body: dict, params: dict) -> tuple[dict, dict]:
            return body, params

        upgrade = OperationUpgrade(
            path="/api/users",
            method="post",
            transformer=transformer,
        )

        assert upgrade.path == "/api/users"
        assert upgrade.method == "post"
        assert upgrade.transformer is transformer

    def test_transformer_can_modify_body_and_params(self):
        def transformer(body: dict, params: dict) -> tuple[dict, dict]:
            # Example: move 'role' from query param to body
            if "role" in params:
                body["role"] = params.pop("role")
            return body, params

        upgrade = OperationUpgrade(
            path="/api/users",
            method="post",
            transformer=transformer,
        )

        body, params = upgrade.transformer({"name": "Alice"}, {"role": "admin"})
        assert body == {"name": "Alice", "role": "admin"}
        assert params == {}


class TestDataMigrationSet:
    def test_empty_set(self):
        migrations = DataMigrationSet()
        assert migrations.is_empty()
        assert migrations.schema_downgrades == []
        assert migrations.schema_upgrades == []

    def test_not_empty_with_schema_downgrade(self):
        migrations = DataMigrationSet(
            schema_downgrades=[
                SchemaDowngrade("#/components/schemas/PersonOut", lambda d: d),
            ]
        )
        assert not migrations.is_empty()

    def test_get_schema_downgrade_found(self):
        def transformer(data: dict) -> dict:
            return data

        migrations = DataMigrationSet(
            schema_downgrades=[
                SchemaDowngrade("#/components/schemas/PersonOut", transformer),
                SchemaDowngrade("#/components/schemas/AddressOut", lambda d: d),
            ]
        )

        result = migrations.get_schema_downgrade("#/components/schemas/PersonOut")
        assert result is not None
        assert result.transformer is transformer

    def test_get_schema_downgrade_not_found(self):
        migrations = DataMigrationSet(
            schema_downgrades=[
                SchemaDowngrade("#/components/schemas/PersonOut", lambda d: d),
            ]
        )

        result = migrations.get_schema_downgrade("#/components/schemas/Unknown")
        assert result is None

    def test_get_schema_upgrade_found(self):
        def transformer(data: dict) -> dict:
            return data

        migrations = DataMigrationSet(
            schema_upgrades=[
                SchemaUpgrade("#/components/schemas/PersonIn", transformer),
            ]
        )

        result = migrations.get_schema_upgrade("#/components/schemas/PersonIn")
        assert result is not None
        assert result.transformer is transformer

    def test_get_operation_downgrade_found(self):
        def transformer(data: dict, status: int) -> dict:
            return data

        migrations = DataMigrationSet(
            operation_downgrades=[
                OperationDowngrade("/api/users", "get", transformer),
            ]
        )

        result = migrations.get_operation_downgrade("/api/users", "get")
        assert result is not None
        assert result.transformer is transformer

    def test_get_operation_downgrade_not_found_wrong_method(self):
        migrations = DataMigrationSet(
            operation_downgrades=[
                OperationDowngrade("/api/users", "get", lambda d, s: d),
            ]
        )

        result = migrations.get_operation_downgrade("/api/users", "post")
        assert result is None

    def test_get_operation_upgrade_found(self):
        def transformer(body: dict, params: dict) -> tuple[dict, dict]:
            return body, params

        migrations = DataMigrationSet(
            operation_upgrades=[
                OperationUpgrade("/api/users", "post", transformer),
            ]
        )

        result = migrations.get_operation_upgrade("/api/users", "post")
        assert result is not None
