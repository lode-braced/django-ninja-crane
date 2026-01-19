"""
API migration: 3 -> 4

change email to emails list
"""

from crane.delta import VersionDelta
from crane.data_migrations import (
    DataMigrationSet,
    SchemaDowngrade,
    SchemaUpgrade,
)

dependencies: list[tuple[str, str]] = [("test_app.api_migrations.default", "3")]
from_version: str | None = "3"
to_version: str = "4"

delta = VersionDelta.model_validate_json("""
{
    "actions": [
        {
            "action": "operation_modified",
            "path": "/persons/search/model",
            "method": "get",
            "old_openapi_json": {
                "parameters": [
                    {
                        "in": "query",
                        "name": "email",
                        "schema": {
                            "anyOf": [
                                {
                                    "type": "string"
                                },
                                {
                                    "type": "null"
                                }
                            ],
                            "title": "Email"
                        },
                        "required": false
                    }
                ]
            },
            "new_openapi_json": {
                "parameters": [
                    {
                        "in": "query",
                        "name": "emails",
                        "schema": {
                            "anyOf": [
                                {
                                    "items": {
                                        "type": "string"
                                    },
                                    "type": "array"
                                },
                                {
                                    "type": "null"
                                }
                            ],
                            "title": "Emails"
                        },
                        "required": false
                    }
                ]
            },
            "old_params": {
                "query": {
                    "email": {
                        "source": "test_app.api.PersonFilter",
                        "json_schema_specification": {
                            "anyOf": [
                                {
                                    "type": "string"
                                },
                                {
                                    "type": "null"
                                }
                            ],
                            "title": "Email"
                        },
                        "required": false
                    }
                }
            },
            "new_params": {
                "query": {
                    "emails": {
                        "source": "test_app.api.PersonFilter",
                        "json_schema_specification": {
                            "anyOf": [
                                {
                                    "items": {
                                        "type": "string"
                                    },
                                    "type": "array"
                                },
                                {
                                    "type": "null"
                                }
                            ],
                            "title": "Emails"
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
                "parameters": [
                    {
                        "in": "query",
                        "name": "email",
                        "schema": {
                            "anyOf": [
                                {
                                    "type": "string"
                                },
                                {
                                    "type": "null"
                                }
                            ],
                            "title": "Email"
                        },
                        "required": false
                    }
                ]
            },
            "new_openapi_json": {
                "parameters": [
                    {
                        "in": "query",
                        "name": "emails",
                        "schema": {
                            "anyOf": [
                                {
                                    "items": {
                                        "type": "string"
                                    },
                                    "type": "array"
                                },
                                {
                                    "type": "null"
                                }
                            ],
                            "title": "Emails"
                        },
                        "required": false
                    }
                ]
            },
            "old_params": {
                "query": {
                    "email": {
                        "source": "test_app.api.PersonFilter",
                        "json_schema_specification": {
                            "anyOf": [
                                {
                                    "type": "string"
                                },
                                {
                                    "type": "null"
                                }
                            ],
                            "title": "Email"
                        },
                        "required": false
                    }
                }
            },
            "new_params": {
                "query": {
                    "emails": {
                        "source": "test_app.api.PersonFilter",
                        "json_schema_specification": {
                            "anyOf": [
                                {
                                    "items": {
                                        "type": "string"
                                    },
                                    "type": "array"
                                },
                                {
                                    "type": "null"
                                }
                            ],
                            "title": "Emails"
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
            "schema_ref": "#/components/schemas/PersonOut",
            "old_schema": {
                "properties": {
                    "email": {
                        "title": "Email",
                        "type": "string"
                    }
                },
                "required": [
                    "id",
                    "name",
                    "email",
                    "created_at"
                ]
            },
            "new_schema": {
                "properties": {
                    "emails": {
                        "items": {
                            "type": "string"
                        },
                        "title": "Emails",
                        "type": "array"
                    }
                },
                "required": [
                    "id",
                    "name",
                    "emails",
                    "created_at"
                ]
            }
        },
        {
            "action": "schema_definition_modified",
            "schema_ref": "#/components/schemas/ComplexPerson",
            "old_schema": {
                "properties": {
                    "email": {
                        "title": "Email",
                        "type": "string"
                    }
                },
                "required": [
                    "name",
                    "email",
                    "type"
                ]
            },
            "new_schema": {
                "properties": {
                    "emails": {
                        "items": {
                            "type": "string"
                        },
                        "title": "Emails",
                        "type": "array"
                    }
                },
                "required": [
                    "name",
                    "emails",
                    "type"
                ]
            }
        },
        {
            "action": "schema_definition_modified",
            "schema_ref": "#/components/schemas/SimplePerson",
            "old_schema": {
                "properties": {
                    "email": {
                        "title": "Email",
                        "type": "string"
                    }
                },
                "required": [
                    "name",
                    "email",
                    "type"
                ]
            },
            "new_schema": {
                "properties": {
                    "emails": {
                        "items": {
                            "type": "string"
                        },
                        "title": "Emails",
                        "type": "array"
                    }
                },
                "required": [
                    "name",
                    "emails",
                    "type"
                ]
            }
        },
        {
            "action": "schema_definition_modified",
            "schema_ref": "#/components/schemas/PersonFilter",
            "old_schema": {
                "properties": {
                    "email": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "null"
                            }
                        ],
                        "title": "Email"
                    }
                }
            },
            "new_schema": {
                "properties": {
                    "emails": {
                        "anyOf": [
                            {
                                "items": {
                                    "type": "string"
                                },
                                "type": "array"
                            },
                            {
                                "type": "null"
                            }
                        ],
                        "title": "Emails"
                    }
                }
            }
        },
        {
            "action": "schema_definition_modified",
            "schema_ref": "#/components/schemas/PersonIn",
            "old_schema": {
                "properties": {
                    "email": {
                        "title": "Email",
                        "type": "string"
                    }
                },
                "required": [
                    "name",
                    "email"
                ]
            },
            "new_schema": {
                "properties": {
                    "emails": {
                        "items": {
                            "type": "string"
                        },
                        "title": "Emails",
                        "type": "array"
                    }
                },
                "required": [
                    "name",
                    "emails"
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
# Convert emails list back to single email string
def _emails_to_email(data: dict) -> dict:
    """Convert emails list to single email string."""
    emails = data.pop("emails", None)
    if emails:
        data["email"] = emails[0]  # Take first email
    else:
        data["email"] = ""
    return data


def downgrade_person_out(data: dict) -> dict:
    """4 -> 3: Transform person_out for older clients."""
    return _emails_to_email(data)


def downgrade_complex_person(data: dict) -> dict:
    """4 -> 3: Transform complex_person for older clients."""
    return _emails_to_email(data)


def downgrade_simple_person(data: dict) -> dict:
    """4 -> 3: Transform simple_person for older clients."""
    return _emails_to_email(data)


def downgrade_person_filter(data: dict) -> dict:
    """4 -> 3: Transform person_filter for older clients."""
    emails = data.pop("emails", None)
    if emails:
        data["email"] = emails[0]
    else:
        data["email"] = None
    return data


def downgrade_person_in(data: dict) -> dict:
    """4 -> 3: Transform person_in for older clients."""
    return _emails_to_email(data)


# Upgrade transformers (old -> new)
# Convert single email string to emails list
def _email_to_emails(data: dict) -> dict:
    """Convert single email string to emails list."""
    email = data.pop("email", None)
    if email:
        data["emails"] = [email]
    else:
        data["emails"] = []
    return data


def upgrade_person_out(data: dict) -> dict:
    """3 -> 4: Transform person_out from older clients."""
    return _email_to_emails(data)


def upgrade_complex_person(data: dict) -> dict:
    """3 -> 4: Transform complex_person from older clients."""
    return _email_to_emails(data)


def upgrade_simple_person(data: dict) -> dict:
    """3 -> 4: Transform simple_person from older clients."""
    return _email_to_emails(data)


def upgrade_person_filter(data: dict) -> dict:
    """3 -> 4: Transform person_filter from older clients."""
    email = data.pop("email", None)
    if email:
        data["emails"] = [email]
    else:
        data["emails"] = None
    return data


def upgrade_person_in(data: dict) -> dict:
    """3 -> 4: Transform person_in from older clients."""
    return _email_to_emails(data)


data_migrations = DataMigrationSet(
    schema_downgrades=[
        SchemaDowngrade("#/components/schemas/PersonOut", downgrade_person_out),
        SchemaDowngrade("#/components/schemas/ComplexPerson", downgrade_complex_person),
        SchemaDowngrade("#/components/schemas/SimplePerson", downgrade_simple_person),
        SchemaDowngrade("#/components/schemas/PersonFilter", downgrade_person_filter),
        SchemaDowngrade("#/components/schemas/PersonIn", downgrade_person_in),
    ],
    schema_upgrades=[
        SchemaUpgrade("#/components/schemas/PersonOut", upgrade_person_out),
        SchemaUpgrade("#/components/schemas/ComplexPerson", upgrade_complex_person),
        SchemaUpgrade("#/components/schemas/SimplePerson", upgrade_simple_person),
        SchemaUpgrade("#/components/schemas/PersonFilter", upgrade_person_filter),
        SchemaUpgrade("#/components/schemas/PersonIn", upgrade_person_in),
    ],
)
