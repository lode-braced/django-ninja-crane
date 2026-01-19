"""Django middleware for API versioning.

This middleware intercepts requests, extracts the requested API version,
transforms requests to the current version, calls the endpoint, and
transforms responses back to the requested version.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Awaitable

from asgiref.sync import async_to_sync, iscoroutinefunction, markcoroutinefunction
from django.http import HttpRequest, HttpResponse, JsonResponse

from crane.api_version import ApiVersion, PathOperation
from crane.migrations_generator import LoadedMigration, get_known_api_state, load_migrations
from crane.path_rewriting import get_path_rewrites_for_upgrade, rewrite_path
from crane.transformers import (
    get_latest_version,
    transform_request,
    transform_response,
    transform_response_list,
)

if TYPE_CHECKING:
    from crane.versioned_api import VersionedNinjaAPI


def _get_api_state_at_version(
    migrations: list[LoadedMigration],
    target_version: str,
) -> ApiVersion:
    """Reconstruct the API state at a specific version by applying migrations."""
    # Find the index of the target version
    target_idx = -1
    for i, m in enumerate(migrations):
        if m.to_version == target_version:
            target_idx = i
            break

    if target_idx == -1:
        return ApiVersion(path_operations={}, schema_definitions={})

    # Apply migrations up to and including the target version
    return get_known_api_state(migrations[: target_idx + 1])


class _APIContext:
    """Context for a single API's version handling."""

    def __init__(self, api: "VersionedNinjaAPI"):
        self.api = api
        self._migrations: list[LoadedMigration] | None = None
        self._api_states: dict[str, ApiVersion] = {}

    @property
    def migrations(self) -> list[LoadedMigration]:
        """Lazy-load migrations for this API."""
        if self._migrations is None:
            try:
                self._migrations = load_migrations(self.api.migrations_module)
            except Exception:
                self._migrations = []
        return self._migrations

    @property
    def latest_version(self) -> str | None:
        """Get the latest API version."""
        return get_latest_version(self.migrations)

    def get_api_state(self, version: str) -> ApiVersion:
        """Get the API state at a specific version, with caching."""
        if version not in self._api_states:
            self._api_states[version] = _get_api_state_at_version(self.migrations, version)
        return self._api_states[version]


class VersionedAPIMiddleware:
    """Middleware that handles API versioning transformations.

    Works with VersionedNinjaAPI instances registered in the application.

    Usage:
        1. Create VersionedNinjaAPI instances in your urls.py:
            api = VersionedNinjaAPI(api_label="default")
            api.add_router("/persons", persons_router)

        2. Add middleware to settings.py:
            MIDDLEWARE = [
                ...
                "crane.middleware.VersionedAPIMiddleware",
            ]
    """

    sync_capable = True
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        self._api_contexts: dict[str, _APIContext] = {}
        self._url_prefix_map: dict[str, "VersionedNinjaAPI"] | None = None

        # Mark ourselves as a coroutine if get_response is async
        if iscoroutinefunction(self.get_response):
            markcoroutinefunction(self)  # type: ignore

    def _get_url_prefix_map(self) -> dict[str, "VersionedNinjaAPI"]:
        """Build mapping of URL prefixes to APIs (lazy, with caching)."""
        if self._url_prefix_map is not None:
            return self._url_prefix_map

        from crane.versioned_api import VersionedNinjaAPI

        self._url_prefix_map = {}

        # First, try to detect URL prefixes from Django's URL resolver
        self._detect_url_prefixes()

        # Add any APIs that have explicit prefixes
        for key, api in VersionedNinjaAPI.get_registry().items():
            prefix = api.url_prefix
            if prefix and prefix not in self._url_prefix_map:
                self._url_prefix_map[prefix] = api

        return self._url_prefix_map

    def _detect_url_prefixes(self) -> None:
        """Detect URL prefixes by introspecting Django's URL configuration."""
        from crane.versioned_api import VersionedNinjaAPI

        try:
            from django.urls import get_resolver

            resolver = get_resolver()
            for key, api in VersionedNinjaAPI.get_registry().items():
                prefix = self._find_api_prefix(resolver, api)
                if prefix:
                    api.url_prefix = prefix
                    self._url_prefix_map[prefix] = api  # type: ignore
        except Exception:
            pass  # Fall back to explicit/default prefixes

    def _find_api_prefix(self, resolver, target_api: "VersionedNinjaAPI") -> str | None:
        """Recursively search URL patterns to find where an API is mounted."""
        for pattern in resolver.url_patterns:
            # Check if this pattern's namespace matches the API
            if hasattr(pattern, "namespace"):
                if pattern.namespace == target_api.urls_namespace:
                    return "/" + str(pattern.pattern).rstrip("/") + "/"

            # Check nested resolvers
            if hasattr(pattern, "url_patterns"):
                nested = self._find_api_prefix(pattern, target_api)
                if nested:
                    prefix = "/" + str(pattern.pattern).rstrip("/")
                    return prefix + nested

        return None

    def _find_api_for_request(self, request: HttpRequest) -> "VersionedNinjaAPI | None":
        """Find the appropriate API for a request based on URL path."""
        path = request.path
        url_map = self._get_url_prefix_map()

        # Find the longest matching prefix
        best_match: tuple[str, "VersionedNinjaAPI"] | None = None
        for prefix, api in url_map.items():
            if path.startswith(prefix):
                if best_match is None or len(prefix) > len(best_match[0]):
                    best_match = (prefix, api)

        return best_match[1] if best_match else None

    def _get_api_context(self, api: "VersionedNinjaAPI") -> _APIContext:
        """Get or create the context for an API."""
        key = api.registry_key
        if key not in self._api_contexts:
            self._api_contexts[key] = _APIContext(api)
        return self._api_contexts[key]

    def _extract_version(self, request: HttpRequest, api: "VersionedNinjaAPI") -> str:
        """Extract the requested API version from the request."""
        version = request.headers.get(api.version_header)
        if version:
            return version
        return api.default_version

    def _resolve_version(self, version: str, ctx: _APIContext) -> str | None:
        """Resolve 'latest' to actual version, validate version exists."""
        if version == "latest":
            return ctx.latest_version

        # Check if version exists in migrations
        for m in ctx.migrations:
            if m.to_version == version:
                return version

        return None

    def _find_operation(
        self,
        request: HttpRequest,
        version: str,
        api: "VersionedNinjaAPI",
        ctx: _APIContext,
    ) -> PathOperation | None:
        """Find the PathOperation for this request at a specific API version."""
        path = request.path
        method = (request.method or "GET").lower()

        # Get the API state at the specified version
        api_state = ctx.get_api_state(version)

        # Search through all operations in the reconstructed state
        for op_path, operations in api_state.path_operations.items():
            if self._path_matches(op_path, path, api.url_prefix):
                for op in operations:
                    if op.method == method:
                        return op

        return None

    def _path_matches(self, template: str, path: str, url_prefix: str) -> bool:
        """Check if a path matches a template with parameters."""
        # Remove api prefix from path for comparison
        if path.startswith(url_prefix):
            path = path[len(url_prefix) - 1 :]

        # Convert template params like {person_id} to regex
        pattern = re.sub(r"\{[^}]+\}", r"[^/]+", template)
        pattern = f"^{pattern}$"
        return bool(re.match(pattern, path))

    def _rewrite_path(
        self,
        request: HttpRequest,
        from_version: str,
        to_version: str,
        api: "VersionedNinjaAPI",
        ctx: _APIContext,
    ) -> None:
        """Rewrite the request path if it changed between versions."""
        # Get path rewrites needed for this version upgrade
        rewrites = get_path_rewrites_for_upgrade(ctx.migrations, from_version, to_version)
        if not rewrites:
            return

        # Extract the API path (without prefix)
        prefix = api.url_prefix.rstrip("/")
        if request.path.startswith(prefix):
            api_path = request.path[len(prefix) :]
        else:
            api_path = request.path

        # Apply rewrites
        method = (request.method or "GET").lower()
        new_api_path = rewrite_path(api_path, method, rewrites)  # type: ignore[arg-type]

        if new_api_path != api_path:
            # Rebuild full path with prefix
            new_path = prefix + new_api_path

            # Store original path for reference
            request.original_path = request.path  # type: ignore[attr-defined]

            # Rewrite the path
            request.path = new_path
            request.path_info = new_path

    def __call__(self, request: HttpRequest) -> HttpResponse | Awaitable[HttpResponse]:
        """Middleware entry point - dispatches to sync or async implementation."""
        if iscoroutinefunction(self):
            return self._async_call(request)
        return self._sync_call(request)

    def _sync_call(self, request: HttpRequest) -> HttpResponse:
        """Synchronous middleware implementation."""
        # Find the API for this request
        api = self._find_api_for_request(request)
        if api is None:
            return self.get_response(request)

        ctx = self._get_api_context(api)

        # Skip if no migrations
        if not ctx.migrations:
            return self.get_response(request)

        # Extract and resolve version
        requested_version = self._extract_version(request, api)
        resolved_version = self._resolve_version(requested_version, ctx)

        if resolved_version is None:
            return JsonResponse(
                {"error": f"Unknown API version: {requested_version}"},
                status=400,
            )

        latest = ctx.latest_version
        if latest is None:
            return JsonResponse(
                {"error": "No API versions available"},
                status=500,
            )

        # Store version info on request for use by views
        request.api_version = resolved_version  # type: ignore
        request.api_latest_version = latest  # type: ignore

        # Rewrite path if needed (handles URL changes across versions)
        if resolved_version != latest:
            self._rewrite_path(request, resolved_version, latest, api, ctx)

        # Find operation metadata at the requested version
        operation = self._find_operation(request, resolved_version, api, ctx)

        # Transform request if needed (upgrade from old version to current)
        if operation and resolved_version != latest:
            self._transform_request_sync(request, operation, resolved_version, latest, ctx)

        # Call the actual view
        response = self.get_response(request)

        # Transform response if needed (downgrade from current to requested version)
        if (
            operation
            and resolved_version != latest
            and isinstance(response, (HttpResponse, JsonResponse))
            and response.get("Content-Type", "").startswith("application/json")
        ):
            response = self._transform_response_sync(
                response, operation, latest, resolved_version, ctx
            )

        return response

    async def _async_call(self, request: HttpRequest) -> HttpResponse:
        """Asynchronous middleware implementation."""
        # Find the API for this request
        api = self._find_api_for_request(request)
        if api is None:
            return await self.get_response(request)

        ctx = self._get_api_context(api)

        # Skip if no migrations
        if not ctx.migrations:
            return await self.get_response(request)

        # Extract and resolve version
        requested_version = self._extract_version(request, api)
        resolved_version = self._resolve_version(requested_version, ctx)

        if resolved_version is None:
            return JsonResponse(
                {"error": f"Unknown API version: {requested_version}"},
                status=400,
            )

        latest = ctx.latest_version
        if latest is None:
            return JsonResponse(
                {"error": "No API versions available"},
                status=500,
            )

        # Store version info on request for use by views
        request.api_version = resolved_version  # type: ignore
        request.api_latest_version = latest  # type: ignore

        # Rewrite path if needed (handles URL changes across versions)
        if resolved_version != latest:
            self._rewrite_path(request, resolved_version, latest, api, ctx)

        # Find operation metadata at the requested version
        operation = self._find_operation(request, resolved_version, api, ctx)

        # Transform request if needed (upgrade from old version to current)
        if operation and resolved_version != latest:
            await self._transform_request_async(request, operation, resolved_version, latest, ctx)

        # Call the actual view
        response = await self.get_response(request)

        # Transform response if needed (downgrade from current to requested version)
        if (
            operation
            and resolved_version != latest
            and isinstance(response, (HttpResponse, JsonResponse))
            and response.get("Content-Type", "").startswith("application/json")
        ):
            response = await self._transform_response_async(
                response, operation, latest, resolved_version, ctx
            )

        return response

    def _transform_request_sync(
        self,
        request: HttpRequest,
        operation: PathOperation,
        from_version: str,
        to_version: str,
        ctx: _APIContext,
    ) -> None:
        """Transform the request body from old version to current (sync)."""
        async_to_sync(self._transform_request_async)(
            request, operation, from_version, to_version, ctx
        )

    async def _transform_request_async(
        self,
        request: HttpRequest,
        operation: PathOperation,
        from_version: str,
        to_version: str,
        ctx: _APIContext,
    ) -> None:
        """Transform the request body and params from old version to current (async)."""
        # Parse body if JSON, None otherwise (not empty dict - let transformers handle it)
        body: dict | None = None
        if request.content_type == "application/json" and request.body:
            try:
                body = json.loads(request.body)
            except json.JSONDecodeError:
                pass  # body stays None

        query_params = dict(request.GET)

        new_body, new_params = await transform_request(
            body,
            query_params,
            operation,
            ctx.migrations,
            from_version,
            to_version,
        )

        # Update request with transformed data (only if we had a body and it changed)
        if new_body is not None and new_body != body:
            request._body = json.dumps(new_body).encode()  # type: ignore

        # Update query params if changed
        if query_params != new_params:
            request.GET._mutable = True  # type: ignore
            request.GET.clear()
            for key, value in new_params.items():
                if isinstance(value, list):
                    request.GET.setlist(key, value)
                else:
                    request.GET[key] = value

            request.GET._mutable = False  # type: ignore

    def _transform_response_sync(
        self,
        response: HttpResponse,
        operation: PathOperation,
        from_version: str,
        to_version: str,
        ctx: _APIContext,
    ) -> HttpResponse:
        """Transform the response body from current version to requested (sync)."""
        return async_to_sync(self._transform_response_async)(
            response, operation, from_version, to_version, ctx
        )

    async def _transform_response_async(
        self,
        response: HttpResponse,
        operation: PathOperation,
        from_version: str,
        to_version: str,
        ctx: _APIContext,
    ) -> HttpResponse:
        """Transform the response body from current version to requested (async)."""
        try:
            content = response.content.decode("utf-8")
            data = json.loads(content)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return response

        status_code = response.status_code

        # Handle list responses
        if isinstance(data, list):
            transformed = await transform_response_list(
                data,
                status_code,
                operation,
                ctx.migrations,
                from_version,
                to_version,
            )
        else:
            transformed = await transform_response(
                data,
                status_code,
                operation,
                ctx.migrations,
                from_version,
                to_version,
            )

        # Create new response with transformed data
        new_response = JsonResponse(transformed, safe=False, status=status_code)

        # Copy headers from original response
        for header, value in response.items():
            if header.lower() not in ("content-type", "content-length"):
                new_response[header] = value

        return new_response
