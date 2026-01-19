"""VersionedNinjaAPI - NinjaAPI subclass with built-in versioning support."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Optional

from django.conf import settings as django_settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import URLPattern, URLResolver, path
from ninja import NinjaAPI
from ninja.constants import NOT_SET
from ninja.openapi.docs import DocsBase

if TYPE_CHECKING:
    from ninja.types import DictStrAny

VersioningSystem = Literal["numerical", "date", "manual"]

ABS_TPL_PATH = Path(__file__).parent / "templates/crane/"


class VersionedSwagger(DocsBase):
    """Swagger UI docs with API version selector.

    Extends Django Ninja's docs pattern to add a version dropdown that allows
    browsing historical API versions.
    """

    template = "crane/versioned_swagger.html"
    template_cdn = str(ABS_TPL_PATH / "versioned_swagger_cdn.html")
    default_settings = {
        "layout": "BaseLayout",
        "deepLinking": True,
    }

    def __init__(self, settings: Optional["DictStrAny"] = None) -> None:
        self.settings: DictStrAny = {}
        self.settings.update(self.default_settings)
        if settings:
            self.settings.update(settings)

    def render_page(
        self, request: HttpRequest, api: "VersionedNinjaAPI", **kwargs: Any
    ) -> HttpResponse:
        from crane.openapi_version import get_available_versions

        try:
            versions = get_available_versions(api.migrations_module)
        except Exception:
            versions = []

        current_version = request.GET.get("version", "latest")
        openapi_url = self.get_openapi_url(api, kwargs)
        openapi_url_with_version = f"{openapi_url}?version={current_version}"

        settings = self.settings.copy()
        settings["url"] = openapi_url_with_version

        context = {
            "swagger_settings": json.dumps(settings, indent=1),
            "api": api,
            "add_csrf": _csrf_needed(api),
            "versions": versions,
            "current_version": current_version,
            "version_header": api.version_header,
        }
        return _render_template(request, self.template, self.template_cdn, context)


def _render_template(
    request: HttpRequest, template: str, template_cdn: str, context: "DictStrAny"
) -> HttpResponse:
    """Render template, using Django's template loader if crane is in INSTALLED_APPS."""
    if "crane" in django_settings.INSTALLED_APPS:
        return render(request, template, context)
    else:
        return _render_cdn_template(request, template_cdn, context)


def _render_cdn_template(
    request: HttpRequest, template_path: str, context: Optional["DictStrAny"] = None
) -> HttpResponse:
    """Render template from file when crane is not in INSTALLED_APPS."""
    from django.template import RequestContext, Template

    tpl = Template(Path(template_path).read_text())
    html = tpl.render(RequestContext(request, context))
    return HttpResponse(html)


def _csrf_needed(api: "NinjaAPI") -> bool:
    """Check if any of the API's auth handlers require CSRF protection."""
    if not api.auth or api.auth == NOT_SET:
        return False
    return any(getattr(a, "csrf", False) for a in api.auth)  # type: ignore


class VersionedNinjaAPI(NinjaAPI):
    """NinjaAPI subclass with built-in API versioning and migration support.

    Example usage:
        ```python
        api = VersionedNinjaAPI(api_label="default")
        api.add_router("/persons", persons_router)

        urlpatterns = [
            path("api/", api.urls),
        ]
        ```
    """

    _versioned_registry: dict[str, "VersionedNinjaAPI"] = {}

    def __init__(
        self,
        *,
        api_label: str,
        app_label: str | None = None,
        versioning: VersioningSystem = "numerical",
        url_prefix: str | None = None,
        version_header: str = "X-API-Version",
        default_version: str = "latest",
        docs: DocsBase = VersionedSwagger(),
        **kwargs: Any,
    ) -> None:
        """Initialize a versioned API.

        Args:
            api_label: Unique identifier for this API within its app.
            app_label: Django app label. Auto-detected if not provided.
            versioning: Version naming scheme - "numerical" (1, 2, 3...),
                "date" (YYYY-MM-DD), or "manual" (user specifies).
            url_prefix: URL prefix where this API is mounted. Auto-detected if not provided.
            version_header: HTTP header name for version specification.
            default_version: Default version when none specified ("latest" or specific version).
            docs: Docs renderer. Defaults to VersionedSwagger() with version selector.
            **kwargs: Additional arguments passed to NinjaAPI.
        """
        self.api_label = api_label
        self.app_label = app_label or self._auto_detect_app_label()
        self.versioning = versioning
        self._explicit_url_prefix = url_prefix
        self._detected_url_prefix: str | None = None
        self.version_header = version_header
        self.default_version = default_version

        # Validate uniqueness
        registry_key = self.registry_key
        if registry_key in self._versioned_registry:
            raise ValueError(f"VersionedNinjaAPI with key '{registry_key}' already registered")

        super().__init__(docs=docs, **kwargs)

        # Register for discovery by management commands and middleware
        self._versioned_registry[registry_key] = self

    @property
    def registry_key(self) -> str:
        """Get the unique registry key for this API."""
        return f"{self.app_label}.{self.api_label}"

    @property
    def migrations_module(self) -> str:
        """Get the migrations module path for this API."""
        return f"{self.app_label}.api_migrations.{self.api_label}"

    @property
    def url_prefix(self) -> str:
        """Get the URL prefix for this API."""
        if self._explicit_url_prefix:
            return self._explicit_url_prefix
        if self._detected_url_prefix:
            return self._detected_url_prefix
        return "/api/"  # Default fallback

    @url_prefix.setter
    def url_prefix(self, value: str) -> None:
        """Set the URL prefix (used by middleware for auto-detection)."""
        self._detected_url_prefix = value

    @classmethod
    def get_registry(cls) -> dict[str, "VersionedNinjaAPI"]:
        """Get a copy of the registered APIs."""
        return cls._versioned_registry.copy()

    @classmethod
    def get_api(cls, app_label: str, api_label: str) -> "VersionedNinjaAPI | None":
        """Get a registered API by its app_label and api_label."""
        return cls._versioned_registry.get(f"{app_label}.{api_label}")

    @classmethod
    def clear_registry(cls) -> None:
        """Clear the registry. Primarily for testing."""
        cls._versioned_registry.clear()

    def _auto_detect_app_label(self) -> str:
        """Auto-detect the app_label from the calling module."""
        for frame_info in inspect.stack():
            module = inspect.getmodule(frame_info.frame)
            if module is None:
                continue
            if module.__name__ == __name__:
                continue  # Skip this module

            module_parts = module.__name__.split(".")
            # Try to find a Django app config for this module
            for i in range(len(module_parts), 0, -1):
                potential_app = ".".join(module_parts[:i])
                try:
                    from django.apps import apps

                    apps.get_app_config(potential_app)
                    return potential_app
                except LookupError:
                    continue

            # Fall back to the top-level module name
            return module_parts[0]

        raise ValueError("Cannot auto-detect app_label. Please provide it explicitly.")

    def generate_next_version(self) -> str:
        """Generate the next version name based on the versioning system."""
        from crane.migrations_generator import load_migrations

        try:
            migrations = load_migrations(self.migrations_module)
        except Exception:
            migrations = []

        if self.versioning == "numerical":
            if not migrations:
                return "1"
            last_version = migrations[-1].to_version
            # Try to parse as integer
            try:
                return str(int(last_version) + 1)
            except ValueError:
                # Fall back to counting migrations
                return str(len(migrations) + 1)

        elif self.versioning == "date":
            from datetime import date

            return date.today().isoformat()

        else:  # manual
            raise ValueError(
                f"API '{self.registry_key}' uses manual versioning. "
                "Provide an explicit version name."
            )

    @property
    def urls(self) -> tuple[list[URLResolver | URLPattern], str, str]:
        """Get URL patterns with versioned docs support."""
        self._validate()
        return (
            self._get_urls(),
            "ninja",
            self.urls_namespace.split(":")[-1],
        )

    def _get_urls(self) -> list[URLResolver | URLPattern]:
        """Build URL patterns with versioned OpenAPI support."""
        from functools import partial

        from ninja.openapi.urls import get_root_url
        from ninja.openapi.views import openapi_view

        result: list[URLResolver | URLPattern] = []

        if self.openapi_url:
            # Use custom versioned openapi JSON endpoint
            view = partial(self._versioned_openapi_json, api=self)
            if self.docs_decorator:
                view = self.docs_decorator(view)  # type: ignore[assignment]
            result.append(
                path(self.openapi_url.lstrip("/"), view, name="openapi-json"),
            )

            assert self.openapi_url != self.docs_url, (
                "Please use different urls for openapi_url and docs_url"
            )

            if self.docs_url:
                # Use standard docs view - delegates to self.docs.render_page()
                view = partial(openapi_view, api=self)
                if self.docs_decorator:
                    view = self.docs_decorator(view)  # type: ignore[assignment]
                result.append(
                    path(self.docs_url.lstrip("/"), view, name="openapi-view"),
                )

        for prefix, router in self._routers:
            result.extend(router.urls_paths(prefix))

        result.append(get_root_url(self))

        return result

    @staticmethod
    def _versioned_openapi_json(request: HttpRequest, api: "VersionedNinjaAPI") -> HttpResponse:
        """Return OpenAPI schema for a specific version."""
        version = request.GET.get("version", "latest")

        if version == "latest":
            schema = api.get_openapi_schema()
            return JsonResponse(schema, safe=False)

        from crane.openapi_version import get_versioned_openapi

        try:
            schema = get_versioned_openapi(api, api.migrations_module, version)
            return JsonResponse(schema, safe=False)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)
