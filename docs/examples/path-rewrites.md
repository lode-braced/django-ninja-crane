# Path Rewrites

When you rename an endpoint's URL path, you need to rewrite requests from old clients so they reach the new endpoint.
Path rewrites handle this transparently.

## When to Use Path Rewrites

- Renaming a resource: `/persons` → `/people`
- Restructuring URLs: `/users/{id}/posts` → `/posts?user_id={id}`
- Fixing inconsistent naming: `/getUser` → `/users/{id}`

## Basic Example

You're renaming `/persons/{person_id}` to `/people/{person_id}`:

```python
# Old (v1)
@router.get("/persons/{person_id}", response=PersonOut)
def get_person(request, person_id: int):
    return Person.objects.get(id=person_id)


# New (v2)
@router.get("/people/{person_id}", response=PersonOut)
def get_person(request, person_id: int):
    return Person.objects.get(id=person_id)
```

### Generate the Migration

```bash
python manage.py makeapimigrations \
    --label default \
    --app myapp \
    --name "Rename persons to people"
```

The migration will detect that an operation was removed (`/persons/{person_id}`) and added (`/people/{person_id}`) with
the same `operation_id`. It auto-generates a `PathRewrite`:

```python
data_migrations = DataMigrationSet(
    path_rewrites=[
        PathRewrite(
            old_path="/persons/{person_id}",
            new_path="/people/{person_id}",
            methods=["get"],
        ),
    ],
)
```

### How It Works

When a v1 client requests:

```
GET /api/persons/123
X-API-Version: 1
```

The middleware:

1. Detects v1 request
2. Rewrites path to `/api/people/123`
3. Routes to the new endpoint
4. Returns the response (applying any schema transformers)

The client never sees the path change.

## Path Parameters

Path parameters use `{name}` syntax. Parameter values are preserved during rewriting:

```python
PathRewrite(
    old_path="/persons/{person_id}",
    new_path="/people/{person_id}",
)
```

Request `/persons/42` → `/people/42`

### Parameter Renaming

You can rename parameters by using different names:

```python
PathRewrite(
    old_path="/users/{user_id}",
    new_path="/users/{id}",  # parameter renamed
)
```

The value is transferred to the new parameter name.

## Method-Specific Rewrites

By default, a `PathRewrite` applies to all HTTP methods. Use `methods` to restrict:

```python
# Only rewrite GET requests
PathRewrite(
    old_path="/persons/{person_id}",
    new_path="/people/{person_id}",
    methods=["get"],
)

# Rewrite GET, PUT, DELETE but not POST
PathRewrite(
    old_path="/persons/{person_id}",
    new_path="/people/{person_id}",
    methods=["get", "put", "delete"],
)
```

## Multiple Rewrites

You can have multiple path rewrites in a single migration:

```python
data_migrations = DataMigrationSet(
    path_rewrites=[
        PathRewrite(
            old_path="/persons",
            new_path="/people",
            methods=["get", "post"],
        ),
        PathRewrite(
            old_path="/persons/{person_id}",
            new_path="/people/{person_id}",
            methods=["get", "put", "delete"],
        ),
    ],
)
```

## Combining with Schema Changes

Path rewrites often accompany schema changes. The same migration can have both:

```python
data_migrations = DataMigrationSet(
    path_rewrites=[
        PathRewrite(
            old_path="/persons/{person_id}",
            new_path="/people/{person_id}",
        ),
    ],
    schema_downgrades=[
        SchemaDowngrade("#/components/schemas/PersonOut", downgrade_person),
    ],
    schema_upgrades=[
        SchemaUpgrade("#/components/schemas/PersonIn", upgrade_person),
    ],
)
```

Order of operations:

1. Path rewrite (request URL modified)
2. Request upgrade (body transformed)
3. Endpoint called
4. Response downgrade (body transformed back)

## Automatic Detection

The migration generator detects path renames automatically by matching:

- Same `operation_id` (the function name by default)
- Same HTTP method
- Different paths

If your rename isn't detected, ensure the endpoint function name stayed the same.

## Manual Path Rewrites

For complex restructuring that isn't auto-detected, add rewrites manually:

```python
# Complex restructure: nested resource to query param
# /users/{user_id}/posts → /posts?user_id={user_id}

data_migrations = DataMigrationSet(
    path_rewrites=[
        PathRewrite(
            old_path="/users/{user_id}/posts",
            new_path="/posts",
            methods=["get"],
        ),
    ],
    operation_upgrades=[
        # Also need to transform the request to add query param
        OperationUpgrade("/posts", "get", add_user_id_param),
    ],
)


def add_user_id_param(body: dict, params: dict) -> tuple[dict, dict]:
    """Extract user_id from the original path and add as query param."""
    # The middleware captures path params before rewrite
    if "user_id" in params:
        # Already handled
        pass
    return body, params
```

> [!NOTE]
> For complex path restructuring, you may need both a `PathRewrite` and an `OperationUpgrade` to handle parameter
> movement.

## Versioned OpenAPI Docs

An easy way to validate whether your path rewrites are successfully written in your migration, is by checking the
OpenAPI docs for your NinjaAPI.

The versioned OpenAPI schema shows the paths as they existed at each version:

- V1 docs show `/persons/{person_id}`
- V2 docs show `/people/{person_id}`

Clients using the v1 docs will use the old paths, which get rewritten.

## Limitations

Path rewrites work for simple URL structure changes. They don't support:

- Query parameter to path conversion (`/items?id=1` → `/items/1`)
- Complex routing logic (use operation transformers instead)
- Removing path segments (`/api/v1/items` → `/items`)

For these cases, use [Operation Transformers](../advanced/operation-transformers.md) with custom logic.

## Next Steps

- [Modifying a Schema](modifying-schema.md) — Schema transformation examples
- [Operation Transformers](../advanced/operation-transformers.md) — Endpoint-specific logic
- [Migration Files](../concepts/migration-files.md) — Full file format reference
