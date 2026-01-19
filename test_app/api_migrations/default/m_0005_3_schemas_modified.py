"""
API migration: 4 -> 5

3 schemas modified
"""

from crane.delta import VersionDelta
from crane.data_migrations import (
    DataMigrationSet,
    SchemaDowngrade,
    SchemaUpgrade,
)

dependencies: list[tuple[str, str]] = [("test_app.api_migrations.default", "4")]
from_version: str | None = "4"
to_version: str = "5"

delta = VersionDelta.model_validate_json("""
{
    "actions": [
        {
            "action": "schema_definition_modified",
            "schema_ref": "#/components/schemas/SimplePerson",
            "old_schema": {
                "properties": {},
                "required": [
                    "name",
                    "emails",
                    "type"
                ]
            },
            "new_schema": {
                "properties": {
                    "address": {
                        "title": "Address",
                        "type": "string"
                    }
                },
                "required": [
                    "name",
                    "emails",
                    "address",
                    "type"
                ]
            }
        },
        {
            "action": "schema_definition_modified",
            "schema_ref": "#/components/schemas/ComplexPerson",
            "old_schema": {
                "properties": {},
                "required": [
                    "name",
                    "emails",
                    "type"
                ]
            },
            "new_schema": {
                "properties": {
                    "address": {
                        "title": "Address",
                        "type": "string"
                    }
                },
                "required": [
                    "name",
                    "emails",
                    "address",
                    "type"
                ]
            }
        },
        {
            "action": "schema_definition_modified",
            "schema_ref": "#/components/schemas/PersonIn",
            "old_schema": {
                "properties": {},
                "required": [
                    "name",
                    "emails"
                ]
            },
            "new_schema": {
                "properties": {
                    "address": {
                        "title": "Address",
                        "type": "string"
                    }
                },
                "required": [
                    "name",
                    "emails",
                    "address"
                ]
            }
        }
    ]
}
""")


# === Data Migrations ===
# Transformers for converting data between API versions.
# Implement the NotImplementedError functions before deploying.


# Downgrade transformers (new -> old)
def downgrade_simple_person(data: dict) -> dict:
    """5 -> 4: Transform simple_person for older clients."""
    data.pop("address", None)
    return data


def downgrade_complex_person(data: dict) -> dict:
    """5 -> 4: Transform complex_person for older clients."""
    data.pop("address", None)
    return data


def downgrade_person_in(data: dict) -> dict:
    """5 -> 4: Transform person_in for older clients."""
    data.pop("address", None)
    return data


# Upgrade transformers (old -> new)
def upgrade_simple_person(data: dict) -> dict:
    """4 -> 5: Transform simple_person from older clients."""
    raise NotImplementedError("Provide default value for new field: address")
    # data.setdefault("address", <default_value>)


def upgrade_complex_person(data: dict) -> dict:
    """4 -> 5: Transform complex_person from older clients."""
    raise NotImplementedError("Provide default value for new field: address")
    # data.setdefault("address", <default_value>)


def upgrade_person_in(data: dict) -> dict:
    """4 -> 5: Transform person_in from older clients."""
    raise NotImplementedError("Provide default value for new field: address")
    # data.setdefault("address", <default_value>)


data_migrations = DataMigrationSet(
    schema_downgrades=[
        SchemaDowngrade("#/components/schemas/SimplePerson", downgrade_simple_person),
        SchemaDowngrade("#/components/schemas/ComplexPerson", downgrade_complex_person),
        SchemaDowngrade("#/components/schemas/PersonIn", downgrade_person_in),
    ],
    schema_upgrades=[
        SchemaUpgrade("#/components/schemas/SimplePerson", upgrade_simple_person),
        SchemaUpgrade("#/components/schemas/ComplexPerson", upgrade_complex_person),
        SchemaUpgrade("#/components/schemas/PersonIn", upgrade_person_in),
    ],
)
