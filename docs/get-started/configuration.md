# Configuration Reference

Reference for configuring django-ninja-crane.

## VersionedNinjaAPI

::: crane.VersionedNinjaAPI
    options:
      members: false
      show_bases: false

All standard `NinjaAPI` parameters (like `auth`, `csrf`, `title`, etc.) are also supported.

## Version Naming Schemes

The `versioning` parameter controls how version names are generated:

```python
# Numerical: 1, 2, 3, ...
api = VersionedNinjaAPI(api_label="default", versioning="numerical")

# Date-based: 2024-01-15, 2024-02-20, ...
api = VersionedNinjaAPI(api_label="default", versioning="date")

# Manual: You specify the version name each time
api = VersionedNinjaAPI(api_label="default", versioning="manual")
```

## Multiple APIs

You can have multiple versioned APIs in the same project:

```python
# Public API
public_api = VersionedNinjaAPI(
    api_label="public",
    app_label="myapp",
    version_header="X-Public-API-Version",
)

# Admin API
admin_api = VersionedNinjaAPI(
    api_label="admin",
    app_label="myapp",
    version_header="X-Admin-API-Version",
)

urlpatterns = [
    path("api/v1/", public_api.urls),
    path("admin-api/", admin_api.urls),
]
```

Each API maintains its own migration chain in separate directories:

- `myapp/api_migrations/public/`
- `myapp/api_migrations/admin/`

## Migration Directory Structure

Migrations are stored in your app's `api_migrations` directory, organized by API label:

```
myapp/
├── api_migrations/
│   ├── __init__.py
│   └── default/
│       ├── __init__.py
│       ├── m_0001_initial_api.py
│       └── m_0002_add_phone_field.py
├── api.py
└── models.py
```

The directory structure is created automatically when you run `makeapimigrations` for the first time.

## Version Detection

Clients specify which API version they want using the HTTP header:

```
X-API-Version: 1
```

If no version is specified, the `default_version` is used (typically `"latest"`).

For custom version detection logic (subdomains, cookies, URL paths), see [Custom Version Resolver](../advanced/custom-version-resolver.md).
