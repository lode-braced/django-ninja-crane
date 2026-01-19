# Quickstart

This guide walks you through setting up API versioning in an existing Django Ninja project. By the end, you'll have a versioned API that serves different schema versions to different clients.

## Prerequisites

- Python 3.12+
- Django 6.0+
- Django Ninja 1.5+
- An existing Django Ninja API

## Install django-ninja-crane

```bash
pip install django-ninja-crane
```

## Configure Django

Add the middleware to your `settings.py`:

```python
MIDDLEWARE = [
    # ... other middleware ...
    "crane.middleware.VersionedAPIMiddleware",
]

INSTALLED_APPS = [
    # ...
    "crane",
]
```

## Use VersionedNinjaAPI

Replace your `NinjaAPI` instance with `VersionedNinjaAPI`:

```python
# urls.py
from crane import VersionedNinjaAPI
from myapp.api import router

# Before:
# api = NinjaAPI()

# After:
api = VersionedNinjaAPI(api_label="default", app_label="myapp")
api.add_router("/persons", router)

urlpatterns = [
    path("api/", api.urls),
]
```

The `api_label` identifies this API within your app (you might have multiple APIs). The `app_label` is your Django app name—if omitted, it's auto-detected.

## Create Your First Migration

With your API defined, create the initial migration to capture the current schema:

```bash
python manage.py makeapimigrations --label default --app myapp --name "Initial API"
```

This creates a migration file at `myapp/api_migrations/default/m_0001_initial_api.py` capturing your current API state as version "1".

## Make a Schema Change

Now let's evolve the API. Say you want to change `email: str` to `emails: list[str]`:

```python
# Before
class PersonOut(Schema):
    name: str
    email: str

# After
class PersonOut(Schema):
    name: str
    emails: list[str]
```

## Generate a Migration

Detect and record the change:

```bash
python manage.py makeapimigrations --label default --app myapp --name "Change email to emails list"
```

This creates `m_0002_change_email_to_emails_list.py` with:

- The schema delta (what changed)
- Skeleton transformer functions (you'll implement these)

## Implement Transformers

Open the generated migration file. You'll see skeleton transformer functions with `NotImplementedError`:

```python
# In m_0002_change_email_to_emails_list.py

# ...


def downgrade_person_out(data: dict) -> dict:
    """2 -> 1: Transform response for v1 clients."""
    raise NotImplementedError

def upgrade_person_out(data: dict) -> dict:
    """1 -> 2: Transform request from v1 clients."""
    raise NotImplementedError

data_migrations = DataMigrationSet(
    schema_downgrades=[
        SchemaDowngrade("#/components/schemas/PersonOut", downgrade_person_out),
    ],
    schema_upgrades=[
        SchemaUpgrade("#/components/schemas/PersonOut", upgrade_person_out),
    ],
)
```

Fill in the transformers to convert between the old and new schema shapes:

```python
def downgrade_person_out(data: dict) -> dict:
    """2 -> 1: Transform response for v1 clients."""
    emails = data.pop("emails", [])
    data["email"] = emails[0] if emails else ""
    return data

def upgrade_person_out(data: dict) -> dict:
    """1 -> 2: Transform request from v1 clients."""
    email = data.pop("email", None)
    data["emails"] = [email] if email else []
    return data
```

## Test It

Your API now serves both versions:

```bash
# Request v2 (latest) - returns new schema
curl http://localhost:8000/api/persons/1
# {"name": "Alice", "emails": ["alice@example.com"]}

# Request v1 - returns old schema
curl -H "X-API-Version: 1" http://localhost:8000/api/persons/1
# {"name": "Alice", "email": "alice@example.com"}
```

## Browse Versioned Docs

Visit your API's docs page (e.g., `/api/docs`) to see the Swagger UI with a version selector dropdown. Each version shows the schema as it appeared at that point in time.

## What's Next?

- [Configuration Reference](configuration.md) — All configuration options
- [Migration Files](../concepts/migration-files.md) — Understand the migration file format
- [Modifying a Schema](../examples/modifying-schema.md) — Detailed walkthrough of schema changes
