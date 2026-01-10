"""Django middleware for API versioning.

This middleware intercepts requests, extracts the requested API version,
transforms requests to the current version, calls the endpoint, and
transforms responses back to the requested version.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from asgiref.sync import async_to_sync, iscoroutinefunction, markcoroutinefunction
from django.conf import settings
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


@dataclass
class CraneSettings:
    """Configuration for crane middleware."""

    version_header: str = "X-API-Version"
    version_query_param: str = "api_version"
    default_version: str = "latest"
    migrations_module: str = ""
    api_url_prefix: str = "/api/"

    @classmethod
    def from_django_settings(cls) -> "CraneSettings":
        """Load settings from Django settings.CRANE_SETTINGS."""
        crane_settings = getattr(settings, "CRANE_SETTINGS", {})
        return cls(
            version_header=crane_settings.get("version_header", cls.version_header),
            version_query_param=crane_settings.get("version_query_param", cls.version_query_param),
            default_version=crane_settings.get("default_version", cls.default_version),
            migrations_module=crane_settings.get("migrations_module", cls.migrations_module),
            api_url_prefix=crane_settings.get("api_url_prefix", cls.api_url_prefix),
        )


class VersionedAPIMiddleware:
    """Middleware that handles API versioning transformations.

    Configuration via Django settings:
        CRANE_SETTINGS = {
            "version_header": "X-API-Version",
            "version_query_param": "api_version",
            "default_version": "latest",
            "migrations_module": "myapp.api_migrations",
            "api_url_prefix": "/api/",
        }

    Usage:
        Add to MIDDLEWARE in settings.py:
        MIDDLEWARE = [
            ...
            "crane.middleware.VersionedAPIMiddleware",
        ]
    """

    sync_capable = True
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        self.settings = CraneSettings.from_django_settings()
        self._migrations: list[LoadedMigration] | None = None
        self._api_states: dict[str, ApiVersion] = {}  # Cache of version -> ApiVersion

        # Mark ourselves as a coroutine if get_response is async
        if iscoroutinefunction(self.get_response):
            markcoroutinefunction(self)

    @property
    def migrations(self) -> list[LoadedMigration]:
        """Lazy-load migrations."""
        if self._migrations is None:
            if self.settings.migrations_module:
                self._migrations = load_migrations(self.settings.migrations_module)
            else:
                self._migrations = []
        return self._migrations

    @property
    def latest_version(self) -> str | None:
        """Get the latest API version."""
        return get_latest_version(self.migrations)

    def _get_api_state(self, version: str) -> ApiVersion:
        """Get the API state at a specific version, with caching."""
        if version not in self._api_states:
            self._api_states[version] = _get_api_state_at_version(self.migrations, version)
        return self._api_states[version]

    def _extract_version(self, request: HttpRequest) -> str:
        """Extract the requested API version from the request."""
        # Check header first
        version = request.headers.get(self.settings.version_header)
        if version:
            return version

        # Check query param
        version = request.GET.get(self.settings.version_query_param)
        if version:
            return version

        # Use default
        return self.settings.default_version

    def _resolve_version(self, version: str) -> str | None:
        """Resolve 'latest' to actual version, validate version exists."""
        if version == "latest":
            return self.latest_version

        # Check if version exists in migrations
        for m in self.migrations:
            if m.to_version == version:
                return version

        return None

    def _find_operation(self, request: HttpRequest, version: str) -> PathOperation | None:
        """Find the PathOperation for this request at a specific API version.

        This reconstructs the API state at the given version to find the
        operation as it existed at that point in time. This correctly handles
        operations that were modified, deleted, or recreated across versions.
        """
        path = request.path
        method = request.method.lower()

        # Get the API state at the specified version
        api_state = self._get_api_state(version)

        # Search through all operations in the reconstructed state
        for op_path, operations in api_state.path_operations.items():
            if self._path_matches(op_path, path):
                for op in operations:
                    if op.method == method:
                        return op

        return None

    def _path_matches(self, template: str, path: str) -> bool:
        """Check if a path matches a template with parameters."""
        # Remove api prefix from path for comparison
        if path.startswith(self.settings.api_url_prefix):
            path = path[len(self.settings.api_url_prefix) - 1 :]

        # Convert template params like {person_id} to regex
        pattern = re.sub(r"\{[^}]+\}", r"[^/]+", template)
        pattern = f"^{pattern}$"
        return bool(re.match(pattern, path))

    def _rewrite_path(self, request: HttpRequest, from_version: str, to_version: str) -> None:
        """Rewrite the request path if it changed between versions.

        This allows old clients to continue using old URL paths even after
        endpoints have been renamed.
        """
        # Get path rewrites needed for this version upgrade
        rewrites = get_path_rewrites_for_upgrade(self.migrations, from_version, to_version)
        if not rewrites:
            return

        # Extract the API path (without prefix)
        prefix = self.settings.api_url_prefix.rstrip("/")
        if request.path.startswith(prefix):
            api_path = request.path[len(prefix) :]
        else:
            api_path = request.path

        # Apply rewrites
        method = request.method.lower()
        new_api_path = rewrite_path(api_path, method, rewrites)  # type: ignore[arg-type]

        if new_api_path != api_path:
            # Rebuild full path with prefix
            new_path = prefix + new_api_path

            # Store original path for reference
            request.original_path = request.path  # type: ignore[attr-defined]

            # Rewrite the path
            request.path = new_path
            request.path_info = new_path

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Middleware entry point - dispatches to sync or async implementation."""
        if iscoroutinefunction(self):
            return self._async_call(request)
        return self._sync_call(request)

    def _sync_call(self, request: HttpRequest) -> HttpResponse:
        """Synchronous middleware implementation."""
        # Skip if not an API request
        if not request.path.startswith(self.settings.api_url_prefix):
            return self.get_response(request)

        # Skip if no migrations configured
        if not self.migrations:
            return self.get_response(request)

        # Extract and resolve version
        requested_version = self._extract_version(request)
        resolved_version = self._resolve_version(requested_version)

        if resolved_version is None:
            return JsonResponse(
                {"error": f"Unknown API version: {requested_version}"},
                status=400,
            )

        latest = self.latest_version
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
            self._rewrite_path(request, resolved_version, latest)

        # Find operation metadata at the requested version
        operation = self._find_operation(request, resolved_version)

        # Transform request if needed (upgrade from old version to current)
        if operation and resolved_version != latest:
            self._transform_request_sync(request, operation, resolved_version, latest)

        # Call the actual view
        response = self.get_response(request)

        # Transform response if needed (downgrade from current to requested version)
        if (
            operation
            and resolved_version != latest
            and isinstance(response, (HttpResponse, JsonResponse))
            and response.get("Content-Type", "").startswith("application/json")
        ):
            response = self._transform_response_sync(response, operation, latest, resolved_version)

        return response

    async def _async_call(self, request: HttpRequest) -> HttpResponse:
        """Asynchronous middleware implementation."""
        # Skip if not an API request
        if not request.path.startswith(self.settings.api_url_prefix):
            return await self.get_response(request)

        # Skip if no migrations configured
        if not self.migrations:
            return await self.get_response(request)

        # Extract and resolve version
        requested_version = self._extract_version(request)
        resolved_version = self._resolve_version(requested_version)

        if resolved_version is None:
            return JsonResponse(
                {"error": f"Unknown API version: {requested_version}"},
                status=400,
            )

        latest = self.latest_version
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
            self._rewrite_path(request, resolved_version, latest)

        # Find operation metadata at the requested version
        operation = self._find_operation(request, resolved_version)

        # Transform request if needed (upgrade from old version to current)
        if operation and resolved_version != latest:
            await self._transform_request_async(request, operation, resolved_version, latest)

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
                response, operation, latest, resolved_version
            )

        return response

    def _transform_request_sync(
        self,
        request: HttpRequest,
        operation: PathOperation,
        from_version: str,
        to_version: str,
    ) -> None:
        """Transform the request body from old version to current (sync)."""
        async_to_sync(self._transform_request_async)(request, operation, from_version, to_version)

    # noinspection PyUnreachableCode
    async def _transform_request_async(
        self,
        request: HttpRequest,
        operation: PathOperation,
        from_version: str,
        to_version: str,
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
            self.migrations,
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
    ) -> HttpResponse:
        """Transform the response body from current version to requested (sync)."""
        return async_to_sync(self._transform_response_async)(
            response, operation, from_version, to_version
        )

    async def _transform_response_async(
        self,
        response: HttpResponse,
        operation: PathOperation,
        from_version: str,
        to_version: str,
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
                self.migrations,
                from_version,
                to_version,
            )
        else:
            transformed = await transform_response(
                data,
                status_code,
                operation,
                self.migrations,
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
