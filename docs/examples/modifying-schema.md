# Schema Transformation Patterns

This guide covers common schema changes and the transformers needed to maintain backwards compatibility.

## How Schema Transformers Work

When a client uses an older API version:

- **Requests** are *upgraded*: old format → new format (before your endpoint runs)
- **Responses** are *downgraded*: new format → old format (after your endpoint returns)

Schema transformers apply automatically wherever the schema appears—direct responses, nested objects, or items in arrays.

```python
from crane.data_migrations import (
    DataMigrationSet,
    SchemaDowngrade,
    SchemaUpgrade,
)

data_migrations = DataMigrationSet(
    schema_downgrades=[
        SchemaDowngrade("#/components/schemas/PersonOut", downgrade_person_out),
    ],
    schema_upgrades=[
        SchemaUpgrade("#/components/schemas/PersonIn", upgrade_person_in),
    ],
)
```

## Common Patterns

### Rename a Field

```python
# v1: firstName
# v2: first_name

def downgrade_person(data: dict) -> dict:
    if "first_name" in data:
        data["firstName"] = data.pop("first_name")
    return data

def upgrade_person(data: dict) -> dict:
    if "firstName" in data:
        data["first_name"] = data.pop("firstName")
    return data
```

### Add a New Field

```python
# v1: no is_active field
# v2: is_active: bool

def downgrade_person(data: dict) -> dict:
    data.pop("is_active", None)
    return data

def upgrade_person(data: dict) -> dict:
    data.setdefault("is_active", True)
    return data
```

### Remove a Field

```python
# v1: has legacy_id
# v2: legacy_id removed

def downgrade_person(data: dict) -> dict:
    data["legacy_id"] = data.get("id")  # Reconstruct from other data
    return data

def upgrade_person(data: dict) -> dict:
    data.pop("legacy_id", None)
    return data
```

### Change Field Type

```python
# v1: age as string "25"
# v2: age as integer 25

def downgrade_person(data: dict) -> dict:
    if "age" in data:
        data["age"] = str(data["age"])
    return data

def upgrade_person(data: dict) -> dict:
    if "age" in data:
        data["age"] = int(data["age"])
    return data
```

### Single Value to List

```python
# v1: email: str
# v2: emails: list[str]

def downgrade_person(data: dict) -> dict:
    emails = data.pop("emails", [])
    data["email"] = emails[0] if emails else ""
    return data

def upgrade_person(data: dict) -> dict:
    email = data.pop("email", None)
    data["emails"] = [email] if email else []
    return data
```

> [!NOTE]
> Downgrading loses data (additional emails beyond the first). This is often acceptable since v1 clients can't handle multiple values anyway.

### Optional to Required

```python
# v1: phone: str | None = None
# v2: phone: str (required)

def downgrade_person(data: dict) -> dict:
    # v2 always has phone, nothing to do
    return data

def upgrade_person(data: dict) -> dict:
    data.setdefault("phone", "")  # Provide default for old clients
    return data
```

### Required to Optional

```python
# v1: phone: str (required)
# v2: phone: str | None = None

def downgrade_person(data: dict) -> dict:
    if data.get("phone") is None:
        data["phone"] = ""  # Old schema required this field
    return data

def upgrade_person(data: dict) -> dict:
    # v1 always has phone, nothing to do
    return data
```

### Nested Object Change

```python
# v1: address: str (flat string)
# v2: address: {street: str, city: str, zip: str}

def downgrade_person(data: dict) -> dict:
    address = data.get("address", {})
    if isinstance(address, dict):
        parts = [address.get("street", ""), address.get("city", ""), address.get("zip", "")]
        data["address"] = ", ".join(p for p in parts if p)
    return data

def upgrade_person(data: dict) -> dict:
    address = data.get("address", "")
    if isinstance(address, str):
        data["address"] = {"street": address, "city": "", "zip": ""}
    return data
```

### Enum Value Change

```python
# v1: status in ["active", "inactive"]
# v2: status in ["active", "inactive", "pending"]

def downgrade_person(data: dict) -> dict:
    if data.get("status") == "pending":
        data["status"] = "inactive"  # Map new value to closest old value
    return data

def upgrade_person(data: dict) -> dict:
    # Old values still valid, nothing to do
    return data
```

### Split a Field

```python
# v1: name: str (full name)
# v2: first_name: str, last_name: str

def downgrade_person(data: dict) -> dict:
    first = data.pop("first_name", "")
    last = data.pop("last_name", "")
    data["name"] = f"{first} {last}".strip()
    return data

def upgrade_person(data: dict) -> dict:
    name = data.pop("name", "")
    parts = name.split(" ", 1)
    data["first_name"] = parts[0] if parts else ""
    data["last_name"] = parts[1] if len(parts) > 1 else ""
    return data
```

### Merge Fields

```python
# v1: first_name: str, last_name: str
# v2: full_name: str

def downgrade_person(data: dict) -> dict:
    full_name = data.pop("full_name", "")
    parts = full_name.split(" ", 1)
    data["first_name"] = parts[0] if parts else ""
    data["last_name"] = parts[1] if len(parts) > 1 else ""
    return data

def upgrade_person(data: dict) -> dict:
    first = data.pop("first_name", "")
    last = data.pop("last_name", "")
    data["full_name"] = f"{first} {last}".strip()
    return data
```

## Handling Nested Schemas

Schema transformers apply recursively. If `PersonOut` is nested inside another schema, the transformer applies automatically:

```python
class TeamOut(Schema):
    name: str
    members: list[PersonOut]  # PersonOut transformer applies to each member
```

## Bidirectional Transformers

For schemas used in both requests and responses (like when the same schema is returned after creation), you typically need both upgrade and downgrade transformers:

```python
data_migrations = DataMigrationSet(
    schema_downgrades=[
        SchemaDowngrade("#/components/schemas/PersonOut", downgrade_person),
        SchemaDowngrade("#/components/schemas/PersonIn", downgrade_person),  # Same logic
    ],
    schema_upgrades=[
        SchemaUpgrade("#/components/schemas/PersonOut", upgrade_person),
        SchemaUpgrade("#/components/schemas/PersonIn", upgrade_person),
    ],
)
```

## When Schema Transformers Aren't Enough

Use [Operation Transformers](../advanced/operation-transformers.md) when you need:

- Access to both body and query parameters together
- Different logic based on HTTP status code
- Endpoint-specific transformations that don't apply globally
