
  <img src="https://github.com/lode-braced/django-ninja-crane/raw/main/docs/crane.png" alt="django-ninja-crane" width="200">

# django-ninja-crane

Stripe-style API versioning and migrations for [Django Ninja](https://django-ninja.dev/).

django-ninja-crane enables you to:

- Track API schema changes over time via migration files
- Automatically transform requests/responses between API versions
- Serve older API versions to clients while running only your latest code

For more information, check the [documentation](https://lode-braced.github.io/django-ninja-crane/)

## Installation

```bash
pip install django-ninja-crane
```

Requirements:

- Python 3.12+
- Django 6.0+
- Django Ninja 1.5.1+

## Quick Start

### 1. Create a Versioned API

Replace any `NinjaAPI` instances you want to version with `VersionedNinjaAPI`:

```python
# urls.py
from crane import VersionedNinjaAPI
from myapp.api import router

api = VersionedNinjaAPI(api_label="default", app_label="myapp")
api.add_router("/persons", router)

urlpatterns = [
    path("api/", api.urls),
]
```

### 2. Add the Middleware

```python
# settings.py
INSTALLED_APPS = [
    # ...
    "crane",
]

MIDDLEWARE = [
    # ...
    "crane.middleware.VersionedAPIMiddleware",
]
```

### 3. Save Your Initial API State

Create the first migration to capture your current API as version 1:

```bash
python manage.py makeapimigrations myapp --name "initial"
```

This creates `myapp/api_migrations/default/m_0001_initial.py` which records your API's starting state.

### 4. Make Changes to Your API

Now modify your API schemas. For example, add a `phone` field to `PersonOut`:

```python
class PersonOut(Schema):
    id: int
    name: str
    email: str
    phone: str | None = None  # New field
```

### 5. Create a Migration for the Changes

Generate a migration that captures the difference between your saved state and the current API:

```bash
python manage.py makeapimigrations myapp --name "add_phone_field"
```

This generates `myapp/api_migrations/default/m_0002_add_phone_field.py` containing:

- Schema changes (added/removed/modified fields)
- Operation changes (new endpoints, modified parameters)

### 6. Implement Data Transformers

The generated migration includes skeleton transformer functions. For simple cases (adding optional fields, removing
fields), the generator creates working implementations automatically:

```python
# myapp/api_migrations/default/m_0002_add_phone_field.py (generated)
def downgrade_person_out(data: dict) -> dict:
    """2 -> 1: Transform person_out for older clients."""
    data.pop("phone", None)
    return data


def upgrade_person_in(data: dict) -> dict:
    """1 -> 2: Transform person_in from older clients."""
    data.setdefault("phone", None)
    return data
```

For changes that require manual intervention (e.g., adding required fields, breaking schema changes), the generator
creates functions that `raise NotImplementedError`:

```python
def upgrade_user(data: dict) -> dict:
    """1 -> 2: Transform user from older clients."""
    raise NotImplementedError("Provide default value for new field: email")
    # data.setdefault("email", <default_value>)
```

Replace these with actual implementations before deploying. The `validateapimigrations` command can check for any
remaining `NotImplementedError` calls.

Now clients requesting `X-API-Version: 1` will receive responses without the `phone` field, while your code only handles
the latest version.

## Development

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest

# Lint & format
uv run ruff check .
uv run ruff format .

# Run dev server
uv run python manage.py runserver
```

## Current functionality

The Current functionality covers most common api migration changes:

* adding/removing new schemas
* modifying schema contents
* modifying operation input pramaters

## Limitations

* union fields (AnyOf), discriminated unions are covered by running all transformers of a union when any of the types in
  the union are updated.
* If you remove an endpoint, you need to manually set up a path rewrite pointing it to the new operation to use for that
  request.

## What's next?

* Proper support for discriminated unions
* Management command to remove an old version
* Easier interface for "bring your own version resolver", allowing you to e.g., determine the version from the request's
  user.
* Validation to check whether your defined data migrations cover the schema changes
* Interactive makeapimigrations, prompting whether you want operation or schema migrations for schema changes.
