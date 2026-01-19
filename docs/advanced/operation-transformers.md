# Operation Transformers

Schema transformers apply wherever a schema appears. Sometimes you need **endpoint-specific** logic that:

- Transforms both body and query parameters together
- Has different logic for the same schema on different endpoints
- Handles pagination, filtering, or other endpoint-specific structures

Operation transformers give you full control over a specific endpoint's request or response.

## When to Use Operation Transformers

Use operation transformers when:

- The same schema needs different handling on different endpoints
- You need to transform query parameters alongside the body
- The response structure is endpoint-specific (pagination wrappers, etc.)
- Logic depends on the full request/response context

Use schema transformers when:

- The transformation is the same everywhere the schema appears
- You're just adding/removing/renaming fields

## OperationUpgrade

Transform **incoming requests** for a specific endpoint. Receives both the body and query parameters:

```python
from crane.data_migrations import OperationUpgrade, DataMigrationSet

def upgrade_search_users(
    body: dict,
    params: dict
) -> tuple[dict, dict]:
    """v1 → v2: Move 'role' from query param to request body."""
    if "role" in params:
        role = params.pop("role")
        body["filters"] = body.get("filters", {})
        body["filters"]["role"] = role
    return body, params

data_migrations = DataMigrationSet(
    operation_upgrades=[
        OperationUpgrade(
            path="/users/search",
            method="post",
            transformer=upgrade_search_users,
        ),
    ],
)
```

### Signature

```python
def upgrade_transformer(
    body: dict,          # Request body (empty dict if no body)
    params: dict         # Query parameters
) -> tuple[dict, dict]:  # (new_body, new_params)
    ...
```

## OperationDowngrade

Transform **outgoing responses** for a specific endpoint. Receives the response data and status code:

```python
from crane.data_migrations import OperationDowngrade, DataMigrationSet

def downgrade_list_users(
    data: dict,
    status_code: int
) -> dict:
    """v2 → v1: Flatten paginated response."""
    # v2 returns: {"items": [...], "total": 100, "page": 1}
    # v1 expected: [...]
    if "items" in data:
        return data["items"]
    return data

data_migrations = DataMigrationSet(
    operation_downgrades=[
        OperationDowngrade(
            path="/users",
            method="get",
            transformer=downgrade_list_users,
        ),
    ],
)
```

### Signature

```python
def downgrade_transformer(
    data: dict,         # Response body
    status_code: int    # HTTP status code
) -> dict:              # Transformed response
    ...
```

## Path Matching

Operation transformers match by exact path and method:

```python
OperationUpgrade(
    path="/users/{user_id}",  # Path with parameter placeholder
    method="put",             # HTTP method (lowercase)
    transformer=...,
)
```

The path should match the **current** API path (after any path rewrites).

## Combining with Schema Transformers

Operation transformers run **before** schema transformers for requests, and **after** for responses:

**Request flow:**
```
v1 request
    → OperationUpgrade (if defined)
    → SchemaUpgrade (for each schema in body)
    → endpoint
```

**Response flow:**
```
endpoint
    → SchemaDowngrade (for each schema in response)
    → OperationDowngrade (if defined)
    → v1 response
```

This means:

- `OperationUpgrade` sees the **old** format, schema transformers see the result
- `SchemaDowngrade` runs first, `OperationDowngrade` sees the already-transformed data

## Async Transformers

Operation transformers can be async for database lookups or API calls:

```python
async def upgrade_create_user(body: dict, params: dict) -> tuple[dict, dict]:
    """Look up team ID from legacy team name."""
    if "team_name" in body:
        team_name = body.pop("team_name")
        team = await Team.objects.aget(name=team_name)
        body["team_id"] = team.id
    return body, params

async def downgrade_get_user(data: dict, status_code: int) -> dict:
    """Add legacy fields for v1 clients."""
    if "team_id" in data:
        team = await Team.objects.aget(id=data["team_id"])
        data["team_name"] = team.name
    return data
```

## Examples

### Pagination Change

v1 returned a flat list, v2 returns paginated:

```python
# v1: GET /items → [item1, item2, ...]
# v2: GET /items → {"items": [...], "total": 100, "next": "/items?page=2"}

def downgrade_list_items(data: dict, status_code: int) -> dict:
    """v2 → v1: Return just the items array."""
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    return data

def upgrade_list_items(body: dict, params: dict) -> tuple[dict, dict]:
    """v1 → v2: Add default pagination params."""
    params.setdefault("page", ["1"])
    params.setdefault("page_size", ["20"])
    return body, params
```

### Parameter Restructuring

v1 had flat query params, v2 uses nested filters:

```python
# v1: GET /users?name=alice&role=admin
# v2: GET /users?filters={"name":"alice","role":"admin"}

import json

def upgrade_search_users(body: dict, params: dict) -> tuple[dict, dict]:
    """v1 → v2: Nest filter params."""
    filters = {}
    for key in ["name", "role", "status"]:
        if key in params:
            value = params.pop(key)
            filters[key] = value[0] if isinstance(value, list) else value

    if filters:
        params["filters"] = [json.dumps(filters)]

    return body, params

def downgrade_search_users(body: dict, params: dict) -> tuple[dict, dict]:
    """v2 → v1: Flatten filter params."""
    if "filters" in params:
        filters_str = params.pop("filters")
        if isinstance(filters_str, list):
            filters_str = filters_str[0]
        filters = json.loads(filters_str)
        for key, value in filters.items():
            params[key] = [value]

    return body, params
```

### Status Code Dependent Response

Different transformation based on success/error:

```python
def downgrade_create_user(data: dict, status_code: int) -> dict:
    """v2 → v1: Handle different response formats."""
    if status_code == 201:
        # Success: remove new fields
        data.pop("created_at", None)
        data.pop("updated_at", None)
    elif status_code >= 400:
        # Error: transform error format
        # v2: {"detail": "...", "code": "..."}
        # v1: {"error": "..."}
        if "detail" in data:
            return {"error": data["detail"]}

    return data
```

### Conditional Field Inclusion

Include/exclude fields based on query params:

```python
def downgrade_get_user(data: dict, status_code: int) -> dict:
    """v2 → v1: Remove fields that didn't exist in v1."""
    # v1 didn't have detailed mode
    data.pop("permissions", None)
    data.pop("activity_log", None)
    data.pop("settings", None)
    return data
```

## Multiple Operations

You can have multiple operation transformers in the same migration:

```python
data_migrations = DataMigrationSet(
    operation_upgrades=[
        OperationUpgrade("/users", "post", upgrade_create_user),
        OperationUpgrade("/users/search", "post", upgrade_search_users),
        OperationUpgrade("/users/{user_id}", "put", upgrade_update_user),
    ],
    operation_downgrades=[
        OperationDowngrade("/users", "get", downgrade_list_users),
        OperationDowngrade("/users/{user_id}", "get", downgrade_get_user),
    ],
)
```

## Interaction with Path Rewrites

If you have both a path rewrite and an operation transformer, use the **new** path in the transformer:

```python
data_migrations = DataMigrationSet(
    path_rewrites=[
        PathRewrite(
            old_path="/persons/{person_id}",
            new_path="/people/{person_id}",
        ),
    ],
    operation_downgrades=[
        # Use the NEW path
        OperationDowngrade("/people/{person_id}", "get", downgrade_get_person),
    ],
)
```

The path rewrite happens first, then the operation transformer.

## Testing

```python
import pytest

def test_upgrade_search_users():
    body = {}
    params = {"role": ["admin"], "name": ["alice"]}

    new_body, new_params = upgrade_search_users(body, params)

    assert "role" not in new_params
    assert new_body["filters"]["role"] == "admin"

def test_downgrade_list_items():
    data = {"items": [{"id": 1}, {"id": 2}], "total": 2}

    result = downgrade_list_items(data, 200)

    assert result == [{"id": 1}, {"id": 2}]
```
