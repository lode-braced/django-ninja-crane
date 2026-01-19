"""
API migration: 2 -> 3

add zip code to address
"""

from crane.delta import VersionDelta
from crane.data_migrations import (
    DataMigrationSet,
    SchemaDowngrade,
    SchemaUpgrade,
)

dependencies: list[tuple[str, str]] = [("test_app.api_migrations.default", "2")]
from_version: str | None = "2"
to_version: str = "3"

delta = VersionDelta.model_validate_json("""
{
    "actions": [
        {
            "action": "operation_modified",
            "path": "/persons/search/model",
            "method": "get",
            "old_openapi_json": {
                "parameters": []
            },
            "new_openapi_json": {
                "parameters": [
                    {
                        "in": "query",
                        "name": "zip_code",
                        "schema": {
                            "anyOf": [
                                {
                                    "type": "string"
                                },
                                {
                                    "type": "null"
                                }
                            ],
                            "title": "Zip Code"
                        },
                        "required": false
                    }
                ]
            },
            "old_params": {},
            "new_params": {
                "query": {
                    "zip_code": {
                        "source": "test_app.api.PersonAddress",
                        "json_schema_specification": {
                            "anyOf": [
                                {
                                    "type": "string"
                                },
                                {
                                    "type": "null"
                                }
                            ],
                            "title": "Zip Code"
                        },
                        "required": false
                    }
                }
            },
            "old_body_refs": [],
            "new_body_refs": [],
            "old_response_refs": [],
            "new_response_refs": []
        },
        {
            "action": "operation_modified",
            "path": "/persons/search/merged",
            "method": "get",
            "old_openapi_json": {
                "parameters": []
            },
            "new_openapi_json": {
                "parameters": [
                    {
                        "in": "query",
                        "name": "zip_code",
                        "schema": {
                            "anyOf": [
                                {
                                    "type": "string"
                                },
                                {
                                    "type": "null"
                                }
                            ],
                            "title": "Zip Code"
                        },
                        "required": false
                    }
                ]
            },
            "old_params": {},
            "new_params": {
                "query": {
                    "zip_code": {
                        "source": "test_app.api.PersonAddress",
                        "json_schema_specification": {
                            "anyOf": [
                                {
                                    "type": "string"
                                },
                                {
                                    "type": "null"
                                }
                            ],
                            "title": "Zip Code"
                        },
                        "required": false
                    }
                }
            },
            "old_body_refs": [],
            "new_body_refs": [],
            "old_response_refs": [],
            "new_response_refs": []
        },
        {
            "action": "schema_definition_modified",
            "schema_ref": "#/components/schemas/PersonAddress",
            "old_schema": {
                "properties": {}
            },
            "new_schema": {
                "properties": {
                    "zip_code": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "null"
                            }
                        ],
                        "title": "Zip Code"
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
def downgrade_person_address(data: dict) -> dict:
    """3 -> 2: Transform person_address for older clients."""
    data.pop("zip_code", None)
    return data


# Upgrade transformers (old -> new)
def upgrade_person_address(data: dict) -> dict:
    """2 -> 3: Transform person_address from older clients."""
    data.setdefault("zip_code", None)
    return data


data_migrations = DataMigrationSet(
    schema_downgrades=[
        SchemaDowngrade("#/components/schemas/PersonAddress", downgrade_person_address),
    ],
    schema_upgrades=[
        SchemaUpgrade("#/components/schemas/PersonAddress", upgrade_person_address),
    ],
)
