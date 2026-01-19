# Custom Version Resolver

By default, django-ninja-crane detects the API version from the HTTP header (`X-API-Version`).

You can customize this to use subdomains, URL paths, cookies, query parameters, or any other mechanism by subclassing `VersionedAPIMiddleware`.

## Subclassing the Middleware

Override the `_extract_version` method to implement your custom logic:

```python
from crane.middleware import VersionedAPIMiddleware

class MyVersionMiddleware(VersionedAPIMiddleware):
    def _extract_version(self, request, api) -> str:
        # Your custom logic here

        # Priority: subdomain > header > cookie > default
        version = self._from_subdomain(request)
        if version:
            return version

        version = request.headers.get(api.version_header)
        if version:
            return version

        version = request.COOKIES.get("api_version")
        if version:
            return version

        return api.default_version

    def _from_subdomain(self, request) -> str | None:
        host = request.get_host()
        if host.startswith("v"):
            return host.split(".")[0][1:]
        return None
```

Register in settings:

```python
MIDDLEWARE = [
    # ...
    "myapp.middleware.MyVersionMiddleware",  # Instead of VersionedAPIMiddleware
]
```

## Version Validation

The middleware validates that the requested version exists. If you want custom validation:

```python
class StrictVersionMiddleware(VersionedAPIMiddleware):
    def _resolve_version(self, version: str, ctx) -> str | None:
        # Only allow specific versions
        allowed = {"1", "2", "latest"}
        if version not in allowed:
            return None

        return super()._resolve_version(version, ctx)
```

## Common Patterns

### Subdomain Versioning

Extract version from subdomain like `v1.api.example.com`:

```python
class SubdomainVersionMiddleware(VersionedAPIMiddleware):
    def _extract_version(self, request, api) -> str:
        host = request.get_host()
        if host.startswith("v") and "." in host:
            return host.split(".")[0][1:]  # "v1.api.example.com" → "1"
        return super()._extract_version(request, api)
```

### URL Path Versioning

Extract version from URL path like `/api/v1/users`:

```python
class PathVersionMiddleware(VersionedAPIMiddleware):
    def _extract_version(self, request, api) -> str:
        path = request.path
        for part in path.split("/"):
            if part.startswith("v") and part[1:].isdigit():
                return part[1:]  # "/api/v1/users" → "1"
        return super()._extract_version(request, api)
```

> [!WARNING]
> URL path versioning requires careful URL configuration. Each version path must route to the same API, and you may need to strip the version prefix before processing.

### Cookie-Based Versioning

Store the version preference in a cookie (useful for browser clients):

```python
class CookieVersionMiddleware(VersionedAPIMiddleware):
    def _extract_version(self, request, api) -> str:
        version = request.COOKIES.get("api_version")
        if version:
            return version
        return super()._extract_version(request, api)
```

### User-Based Versioning

Different users on different versions (assuming your user model has a `api_version` attribute.

```python
class UserVersionMiddleware(VersionedAPIMiddleware):
    def _extract_version(self, request, api) -> str:
        if hasattr(request, 'user') and request.user.is_authenticated:
            version = getattr(request.user, 'api_version', None)
            if version:
                return version
        return super()._extract_version(request, api)
```

## Combining Multiple Strategies

You can combine strategies with fallback:

```python
class FlexibleVersionMiddleware(VersionedAPIMiddleware):
    def _extract_version(self, request, api) -> str:
        # Try each strategy in order
        strategies = [
            self._from_subdomain,
            self._from_cookie,
            self._from_user,
        ]

        for strategy in strategies:
            version = strategy(request)
            if version:
                return version

        # Fall back to default header-based extraction
        return super()._extract_version(request, api)

    def _from_subdomain(self, request) -> str | None:
        host = request.get_host()
        if host.startswith("v") and "." in host:
            return host.split(".")[0][1:]
        return None

    def _from_cookie(self, request) -> str | None:
        return request.COOKIES.get("api_version")

    def _from_user(self, request) -> str | None:
        if hasattr(request, 'user') and request.user.is_authenticated:
            return getattr(request.user, 'api_version', None)
        return None
```
