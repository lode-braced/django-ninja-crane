"""API migration: empty -> v1

Initial API version
"""

from crane.delta import VersionDelta

dependencies: list[tuple[str, str]] = []
from_version: str | None = None
to_version: str = "v1"

delta = VersionDelta.model_validate_json("""
{
    "actions": [
        {
            "action": "operation_added",
            "path": "/persons/{person_id}",
            "method": "get",
            "new_operation": {
                "method": "get",
                "query_params": {},
                "path_params": {
                    "person_id": {
                        "source": null,
                        "json_schema_specification": {
                            "title": "Person Id",
                            "type": "integer"
                        },
                        "required": true
                    }
                },
                "cookie_params": {},
                "request_body_schema": [],
                "response_bodies": [
                    "#/components/schemas/PersonOut"
                ],
                "operation_id": "test_app_api_get_person",
                "path": "/persons/{person_id}",
                "openapi_json": {
                    "operationId": "test_app_api_get_person",
                    "summary": "Get Person",
                    "parameters": [
                        {
                            "in": "path",
                            "name": "person_id",
                            "schema": {
                                "title": "Person Id",
                                "type": "integer"
                            },
                            "required": true
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/PersonOut"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        {
            "action": "operation_added",
            "path": "/persons/search/model",
            "method": "get",
            "new_operation": {
                "method": "get",
                "query_params": {
                    "name": {
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
                            "title": "Name"
                        },
                        "required": false
                    },
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
                    },
                    "street": {
                        "source": "test_app.api.PersonAddress",
                        "json_schema_specification": {
                            "title": "Street",
                            "type": "string"
                        },
                        "required": true
                    },
                    "city": {
                        "source": "test_app.api.PersonAddress",
                        "json_schema_specification": {
                            "title": "City",
                            "type": "string"
                        },
                        "required": true
                    }
                },
                "path_params": {},
                "cookie_params": {},
                "request_body_schema": [],
                "response_bodies": [
                    "#/components/schemas/PersonOut"
                ],
                "operation_id": "test_app_api_search_persons_model",
                "path": "/persons/search/model",
                "openapi_json": {
                    "operationId": "test_app_api_search_persons_model",
                    "summary": "Search Persons Model",
                    "parameters": [
                        {
                            "in": "query",
                            "name": "name",
                            "schema": {
                                "anyOf": [
                                    {
                                        "type": "string"
                                    },
                                    {
                                        "type": "null"
                                    }
                                ],
                                "title": "Name"
                            },
                            "required": false
                        },
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
                        },
                        {
                            "in": "query",
                            "name": "street",
                            "schema": {
                                "title": "Street",
                                "type": "string"
                            },
                            "required": true
                        },
                        {
                            "in": "query",
                            "name": "city",
                            "schema": {
                                "title": "City",
                                "type": "string"
                            },
                            "required": true
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "additionalProperties": {
                                            "$ref": "#/components/schemas/PersonOut"
                                        },
                                        "title": "Response",
                                        "type": "object"
                                    }
                                }
                            }
                        }
                    },
                    "description": "Query params as a model."
                }
            }
        },
        {
            "action": "operation_added",
            "path": "/persons/upload",
            "method": "post",
            "new_operation": {
                "method": "post",
                "query_params": {},
                "path_params": {},
                "cookie_params": {},
                "request_body_schema": [
                    "#/components/schemas/SimplePerson",
                    "#/components/schemas/ComplexPerson"
                ],
                "response_bodies": [],
                "operation_id": "test_app_api_upload_file",
                "path": "/persons/upload",
                "openapi_json": {
                    "operationId": "test_app_api_upload_file",
                    "summary": "Upload File",
                    "parameters": [],
                    "responses": {
                        "200": {
                            "description": "OK"
                        }
                    },
                    "description": "Multipart file upload endpoint.",
                    "requestBody": {
                        "content": {
                            "multipart/form-data": {
                                "schema": {
                                    "properties": {
                                        "file_up": {
                                            "format": "binary",
                                            "title": "File Up",
                                            "type": "string"
                                        },
                                        "body": {
                                            "discriminator": {
                                                "mapping": {
                                                    "complex": "#/components/schemas/ComplexPerson",
                                                    "simple": "#/components/schemas/SimplePerson"
                                                },
                                                "propertyName": "type"
                                            },
                                            "oneOf": [
                                                {
                                                    "$ref": "#/components/schemas/SimplePerson"
                                                },
                                                {
                                                    "$ref": "#/components/schemas/ComplexPerson"
                                                }
                                            ],
                                            "title": "Body"
                                        }
                                    },
                                    "required": [
                                        "file_up",
                                        "body"
                                    ],
                                    "title": "MultiPartBodyParams",
                                    "type": "object"
                                }
                            }
                        },
                        "required": true
                    }
                }
            }
        },
        {
            "action": "operation_added",
            "path": "/persons/search/primitive",
            "method": "get",
            "new_operation": {
                "method": "get",
                "query_params": {
                    "name": {
                        "source": null,
                        "json_schema_specification": {
                            "anyOf": [
                                {
                                    "type": "string"
                                },
                                {
                                    "type": "null"
                                }
                            ],
                            "title": "Name"
                        },
                        "required": false
                    },
                    "limit": {
                        "source": null,
                        "json_schema_specification": {
                            "default": 10,
                            "title": "Limit",
                            "type": "integer"
                        },
                        "required": false
                    }
                },
                "path_params": {},
                "cookie_params": {},
                "request_body_schema": [],
                "response_bodies": [
                    "#/components/schemas/PersonOut"
                ],
                "operation_id": "test_app_api_search_persons_primitive",
                "path": "/persons/search/primitive",
                "openapi_json": {
                    "operationId": "test_app_api_search_persons_primitive",
                    "summary": "Search Persons Primitive",
                    "parameters": [
                        {
                            "in": "query",
                            "name": "name",
                            "schema": {
                                "anyOf": [
                                    {
                                        "type": "string"
                                    },
                                    {
                                        "type": "null"
                                    }
                                ],
                                "title": "Name"
                            },
                            "required": false
                        },
                        {
                            "in": "query",
                            "name": "limit",
                            "schema": {
                                "default": 10,
                                "title": "Limit",
                                "type": "integer"
                            },
                            "required": false
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "items": {
                                            "$ref": "#/components/schemas/PersonOut"
                                        },
                                        "title": "Response",
                                        "type": "array"
                                    }
                                }
                            }
                        }
                    },
                    "description": "Query params as primitive annotations."
                }
            }
        },
        {
            "action": "operation_added",
            "path": "/persons/",
            "method": "get",
            "new_operation": {
                "method": "get",
                "query_params": {},
                "path_params": {},
                "cookie_params": {},
                "request_body_schema": [],
                "response_bodies": [
                    "#/components/schemas/PersonOut"
                ],
                "operation_id": "test_app_api_list_persons",
                "path": "/persons/",
                "openapi_json": {
                    "operationId": "test_app_api_list_persons",
                    "summary": "List Persons",
                    "parameters": [],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "items": {
                                            "$ref": "#/components/schemas/PersonOut"
                                        },
                                        "title": "Response",
                                        "type": "array"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        {
            "action": "operation_added",
            "path": "/persons/",
            "method": "post",
            "new_operation": {
                "method": "post",
                "query_params": {},
                "path_params": {},
                "cookie_params": {},
                "request_body_schema": [
                    "#/components/schemas/PersonIn"
                ],
                "response_bodies": [
                    "#/components/schemas/PersonOut"
                ],
                "operation_id": "test_app_api_create_person",
                "path": "/persons/",
                "openapi_json": {
                    "operationId": "test_app_api_create_person",
                    "summary": "Create Person",
                    "parameters": [],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/PersonOut"
                                    }
                                }
                            }
                        }
                    },
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/PersonIn"
                                }
                            }
                        },
                        "required": true
                    }
                }
            }
        },
        {
            "action": "operation_added",
            "path": "/persons/search/merged",
            "method": "get",
            "new_operation": {
                "method": "get",
                "query_params": {
                    "name": {
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
                            "title": "Name"
                        },
                        "required": false
                    },
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
                    },
                    "street": {
                        "source": "test_app.api.PersonAddress",
                        "json_schema_specification": {
                            "title": "Street",
                            "type": "string"
                        },
                        "required": true
                    },
                    "city": {
                        "source": "test_app.api.PersonAddress",
                        "json_schema_specification": {
                            "title": "City",
                            "type": "string"
                        },
                        "required": true
                    },
                    "page": {
                        "source": "test_app.api.PaginationParams",
                        "json_schema_specification": {
                            "default": 1,
                            "title": "Page",
                            "type": "integer"
                        },
                        "required": false
                    },
                    "page_size": {
                        "source": "test_app.api.PaginationParams",
                        "json_schema_specification": {
                            "default": 20,
                            "title": "Page Size",
                            "type": "integer"
                        },
                        "required": false
                    }
                },
                "path_params": {},
                "cookie_params": {},
                "request_body_schema": [],
                "response_bodies": [
                    "#/components/schemas/PersonOut"
                ],
                "operation_id": "test_app_api_search_persons_merged",
                "path": "/persons/search/merged",
                "openapi_json": {
                    "operationId": "test_app_api_search_persons_merged",
                    "summary": "Search Persons Merged",
                    "parameters": [
                        {
                            "in": "query",
                            "name": "name",
                            "schema": {
                                "anyOf": [
                                    {
                                        "type": "string"
                                    },
                                    {
                                        "type": "null"
                                    }
                                ],
                                "title": "Name"
                            },
                            "required": false
                        },
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
                        },
                        {
                            "in": "query",
                            "name": "street",
                            "schema": {
                                "title": "Street",
                                "type": "string"
                            },
                            "required": true
                        },
                        {
                            "in": "query",
                            "name": "city",
                            "schema": {
                                "title": "City",
                                "type": "string"
                            },
                            "required": true
                        },
                        {
                            "in": "query",
                            "name": "page",
                            "schema": {
                                "default": 1,
                                "title": "Page",
                                "type": "integer"
                            },
                            "required": false
                        },
                        {
                            "in": "query",
                            "name": "page_size",
                            "schema": {
                                "default": 20,
                                "title": "Page Size",
                                "type": "integer"
                            },
                            "required": false
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "items": {
                                            "$ref": "#/components/schemas/PersonOut"
                                        },
                                        "title": "Response",
                                        "type": "array"
                                    }
                                }
                            }
                        }
                    },
                    "description": "Query params from multiple merged Schema models."
                }
            }
        },
        {
            "action": "operation_added",
            "path": "/persons/upload_file",
            "method": "post",
            "new_operation": {
                "method": "post",
                "query_params": {},
                "path_params": {},
                "cookie_params": {},
                "request_body_schema": [],
                "response_bodies": [],
                "operation_id": "test_app_api_upload_single",
                "path": "/persons/upload_file",
                "openapi_json": {
                    "operationId": "test_app_api_upload_single",
                    "summary": "Upload Single",
                    "parameters": [],
                    "responses": {
                        "200": {
                            "description": "OK"
                        }
                    },
                    "requestBody": {
                        "content": {
                            "multipart/form-data": {
                                "schema": {
                                    "properties": {
                                        "file": {
                                            "format": "binary",
                                            "title": "File",
                                            "type": "string"
                                        }
                                    },
                                    "required": [
                                        "file"
                                    ],
                                    "title": "FileParams",
                                    "type": "object"
                                }
                            }
                        },
                        "required": true
                    }
                }
            }
        },
        {
            "action": "operation_added",
            "path": "/persons/{person_id}",
            "method": "put",
            "new_operation": {
                "method": "put",
                "query_params": {},
                "path_params": {
                    "person_id": {
                        "source": null,
                        "json_schema_specification": {
                            "title": "Person Id",
                            "type": "integer"
                        },
                        "required": true
                    }
                },
                "cookie_params": {},
                "request_body_schema": [
                    "#/components/schemas/PersonIn"
                ],
                "response_bodies": [
                    "#/components/schemas/PersonOut"
                ],
                "operation_id": "test_app_api_update_person",
                "path": "/persons/{person_id}",
                "openapi_json": {
                    "operationId": "test_app_api_update_person",
                    "summary": "Update Person",
                    "parameters": [
                        {
                            "in": "path",
                            "name": "person_id",
                            "schema": {
                                "title": "Person Id",
                                "type": "integer"
                            },
                            "required": true
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/PersonOut"
                                    }
                                }
                            }
                        }
                    },
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/PersonIn"
                                }
                            }
                        },
                        "required": true
                    }
                }
            }
        },
        {
            "action": "operation_added",
            "path": "/persons/{person_id}",
            "method": "delete",
            "new_operation": {
                "method": "delete",
                "query_params": {},
                "path_params": {
                    "person_id": {
                        "source": null,
                        "json_schema_specification": {
                            "title": "Person Id",
                            "type": "integer"
                        },
                        "required": true
                    }
                },
                "cookie_params": {},
                "request_body_schema": [],
                "response_bodies": [],
                "operation_id": "test_app_api_delete_person",
                "path": "/persons/{person_id}",
                "openapi_json": {
                    "operationId": "test_app_api_delete_person",
                    "summary": "Delete Person",
                    "parameters": [
                        {
                            "in": "path",
                            "name": "person_id",
                            "schema": {
                                "title": "Person Id",
                                "type": "integer"
                            },
                            "required": true
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "OK"
                        }
                    }
                }
            }
        },
        {
            "action": "schema_definition_added",
            "schema_ref": "#/components/schemas/PersonAddress",
            "new_schema": {
                "properties": {
                    "street": {
                        "title": "Street",
                        "type": "string"
                    },
                    "city": {
                        "title": "City",
                        "type": "string"
                    }
                },
                "required": [
                    "street",
                    "city"
                ],
                "title": "PersonAddress",
                "type": "object"
            }
        },
        {
            "action": "schema_definition_added",
            "schema_ref": "#/components/schemas/PersonOut",
            "new_schema": {
                "properties": {
                    "id": {
                        "title": "Id",
                        "type": "integer"
                    },
                    "name": {
                        "title": "Name",
                        "type": "string"
                    },
                    "email": {
                        "title": "Email",
                        "type": "string"
                    },
                    "created_at": {
                        "format": "date-time",
                        "title": "Created At",
                        "type": "string"
                    }
                },
                "required": [
                    "id",
                    "name",
                    "email",
                    "created_at"
                ],
                "title": "PersonOut",
                "type": "object"
            }
        },
        {
            "action": "schema_definition_added",
            "schema_ref": "#/components/schemas/ComplexPerson",
            "new_schema": {
                "properties": {
                    "name": {
                        "title": "Name",
                        "type": "string"
                    },
                    "email": {
                        "title": "Email",
                        "type": "string"
                    },
                    "type": {
                        "const": "complex",
                        "title": "Type",
                        "type": "string"
                    }
                },
                "required": [
                    "name",
                    "email",
                    "type"
                ],
                "title": "ComplexPerson",
                "type": "object"
            }
        },
        {
            "action": "schema_definition_added",
            "schema_ref": "#/components/schemas/PaginationParams",
            "new_schema": {
                "properties": {
                    "page": {
                        "default": 1,
                        "title": "Page",
                        "type": "integer"
                    },
                    "page_size": {
                        "default": 20,
                        "title": "Page Size",
                        "type": "integer"
                    }
                },
                "title": "PaginationParams",
                "type": "object"
            }
        },
        {
            "action": "schema_definition_added",
            "schema_ref": "#/components/schemas/SimplePerson",
            "new_schema": {
                "properties": {
                    "name": {
                        "title": "Name",
                        "type": "string"
                    },
                    "email": {
                        "title": "Email",
                        "type": "string"
                    },
                    "type": {
                        "const": "simple",
                        "title": "Type",
                        "type": "string"
                    }
                },
                "required": [
                    "name",
                    "email",
                    "type"
                ],
                "title": "SimplePerson",
                "type": "object"
            }
        },
        {
            "action": "schema_definition_added",
            "schema_ref": "#/components/schemas/PersonIn",
            "new_schema": {
                "properties": {
                    "name": {
                        "title": "Name",
                        "type": "string"
                    },
                    "email": {
                        "title": "Email",
                        "type": "string"
                    }
                },
                "required": [
                    "name",
                    "email"
                ],
                "title": "PersonIn",
                "type": "object"
            }
        },
        {
            "action": "schema_definition_added",
            "schema_ref": "#/components/schemas/PersonFilter",
            "new_schema": {
                "properties": {
                    "name": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "null"
                            }
                        ],
                        "title": "Name"
                    },
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
                    },
                    "address": {
                        "$ref": "#/components/schemas/PersonAddress"
                    }
                },
                "required": [
                    "address"
                ],
                "title": "PersonFilter",
                "type": "object"
            }
        }
    ]
}
""")
