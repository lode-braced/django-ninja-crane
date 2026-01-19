"""
API migration: 1 -> 2

add phone field
"""

from crane.delta import VersionDelta
from crane.data_migrations import (
    DataMigrationSet,
    SchemaDowngrade,
    SchemaUpgrade,
)

dependencies: list[tuple[str, str]] = [("test_app.api_migrations.default", "1")]
from_version: str | None = "1"
to_version: str = "2"

delta = VersionDelta.model_validate_json("""
{
    "actions": [
        {
            "action": "schema_definition_modified",
            "schema_ref": "#/components/schemas/PersonIn",
            "old_schema": {
                "properties": {}
            },
            "new_schema": {
                "properties": {
                    "phone": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "null"
                            }
                        ],
                        "title": "Phone"
                    }
                }
            }
        },
        {
            "action": "schema_definition_modified",
            "schema_ref": "#/components/schemas/ComplexPerson",
            "old_schema": {
                "properties": {}
            },
            "new_schema": {
                "properties": {
                    "phone": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "null"
                            }
                        ],
                        "title": "Phone"
                    }
                }
            }
        },
        {
            "action": "schema_definition_modified",
            "schema_ref": "#/components/schemas/PersonOut",
            "old_schema": {
                "properties": {}
            },
            "new_schema": {
                "properties": {
                    "phone": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "null"
                            }
                        ],
                        "title": "Phone"
                    }
                }
            }
        },
        {
            "action": "schema_definition_modified",
            "schema_ref": "#/components/schemas/SimplePerson",
            "old_schema": {
                "properties": {}
            },
            "new_schema": {
                "properties": {
                    "phone": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "null"
                            }
                        ],
                        "title": "Phone"
                    }
                }
            }
        }
    ]
}
""")


# === Data Migrations ===
# Transformers for converting data between API versions.
# Implement the NotImplementedError functions before deploying.


# Downgrade transformers (new -> old)
def downgrade_person_in(data: dict) -> dict:
    """2 -> 1: Transform person_in for older clients."""
    data.pop("phone", None)
    return data


def downgrade_complex_person(data: dict) -> dict:
    """2 -> 1: Transform complex_person for older clients."""
    data.pop("phone", None)
    return data


def downgrade_person_out(data: dict) -> dict:
    """2 -> 1: Transform person_out for older clients."""
    data.pop("phone", None)
    return data


def downgrade_simple_person(data: dict) -> dict:
    """2 -> 1: Transform simple_person for older clients."""
    data.pop("phone", None)
    return data


# Upgrade transformers (old -> new)
def upgrade_person_in(data: dict) -> dict:
    """1 -> 2: Transform person_in from older clients."""
    data.setdefault("phone", None)
    return data


def upgrade_complex_person(data: dict) -> dict:
    """1 -> 2: Transform complex_person from older clients."""
    data.setdefault("phone", None)
    return data


def upgrade_person_out(data: dict) -> dict:
    """1 -> 2: Transform person_out from older clients."""
    data.setdefault("phone", None)
    return data


def upgrade_simple_person(data: dict) -> dict:
    """1 -> 2: Transform simple_person from older clients."""
    data.setdefault("phone", None)
    return data


data_migrations = DataMigrationSet(
    schema_downgrades=[
        SchemaDowngrade("#/components/schemas/PersonIn", downgrade_person_in),
        SchemaDowngrade("#/components/schemas/ComplexPerson", downgrade_complex_person),
        SchemaDowngrade("#/components/schemas/PersonOut", downgrade_person_out),
        SchemaDowngrade("#/components/schemas/SimplePerson", downgrade_simple_person),
    ],
    schema_upgrades=[
        SchemaUpgrade("#/components/schemas/PersonIn", upgrade_person_in),
        SchemaUpgrade("#/components/schemas/ComplexPerson", upgrade_complex_person),
        SchemaUpgrade("#/components/schemas/PersonOut", upgrade_person_out),
        SchemaUpgrade("#/components/schemas/SimplePerson", upgrade_simple_person),
    ],
)
