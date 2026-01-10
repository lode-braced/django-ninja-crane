"""Path rewriting utilities for version-aware URL resolution.

This module provides utilities to rewrite request paths from old API versions
to current paths before Django's URL resolution.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from crane.data_migrations import PathRewrite
    from crane.delta import HttpMethod
    from crane.migrations_generator import LoadedMigration


def match_path_pattern(pattern: str, path: str) -> dict[str, str] | None:
    """Match a path against a pattern, extracting path parameters.

    Args:
        pattern: Path pattern with {param} placeholders, e.g., "/users/{user_id}"
        path: Actual request path, e.g., "/users/123"

    Returns:
        Dict of param names to values if matched, None if no match.

    Examples:
        >>> match_path_pattern("/users/{id}", "/users/123")
        {"id": "123"}
        >>> match_path_pattern("/users/{id}/posts/{post_id}", "/users/1/posts/42")
        {"id": "1", "post_id": "42"}
        >>> match_path_pattern("/users/{id}", "/posts/123")
        None
    """
    # Extract param names and build regex
    param_names: list[str] = []
    regex_pattern = pattern

    # Find all {param} placeholders
    for match in re.finditer(r"\{([^}]+)\}", pattern):
        param_names.append(match.group(1))

    # Convert {param} to regex capture groups
    # Match any non-slash characters
    regex_pattern = re.sub(r"\{[^}]+\}", r"([^/]+)", regex_pattern)
    regex_pattern = f"^{regex_pattern}$"

    match = re.match(regex_pattern, path)
    if not match:
        return None

    # Build param dict from captured groups
    return dict(zip(param_names, match.groups(), strict=True))


def build_path(pattern: str, params: dict[str, str]) -> str:
    """Build a path from a pattern and parameter values.

    Args:
        pattern: Path pattern with {param} placeholders, e.g., "/people/{person_id}"
        params: Dict of param names to values

    Returns:
        Built path with params substituted.

    Examples:
        >>> build_path("/people/{id}", {"id": "123"})
        "/people/123"
        >>> build_path("/users/{user_id}/posts", {"user_id": "42", "extra": "ignored"})
        "/users/42/posts"
    """
    result = pattern
    for name, value in params.items():
        result = result.replace(f"{{{name}}}", value)
    return result


def get_path_rewrites_for_upgrade(
    migrations: list[LoadedMigration],
    from_version: str,
    to_version: str,
) -> list[PathRewrite]:
    """Get all path rewrites needed to upgrade from one version to another.

    Returns rewrites in order (oldest first) so they can be applied sequentially.

    Args:
        migrations: All loaded migrations
        from_version: The client's requested version (older)
        to_version: The current/target version (newer)

    Returns:
        List of PathRewrite objects to apply in order.
    """
    # Build version to index mapping
    version_to_idx = {m.to_version: i for i, m in enumerate(migrations)}

    if from_version not in version_to_idx or to_version not in version_to_idx:
        return []

    from_idx = version_to_idx[from_version]
    to_idx = version_to_idx[to_version]

    if from_idx >= to_idx:
        # Same version or downgrade - no path rewriting needed for requests
        return []

    # Collect path rewrites from migrations between versions (exclusive of from, inclusive of to)
    rewrites: list[PathRewrite] = []
    for migration in migrations[from_idx + 1 : to_idx + 1]:
        if migration.data_migrations:
            rewrites.extend(migration.data_migrations.path_rewrites)

    return rewrites


def rewrite_path(
    path: str,
    method: HttpMethod,
    rewrites: list[PathRewrite],
) -> str:
    """Apply a sequence of path rewrites to transform a path.

    Args:
        path: The original request path
        method: The HTTP method of the request
        rewrites: List of PathRewrite objects to apply in order

    Returns:
        The rewritten path, or original path if no rewrites matched.
    """
    current_path = path

    for rewrite in rewrites:
        # Check if method matches (None means all methods)
        if rewrite.methods is not None and method not in rewrite.methods:
            continue

        # Try to match against old_path pattern
        params = match_path_pattern(rewrite.old_path, current_path)
        if params is not None:
            # Match found - build new path
            current_path = build_path(rewrite.new_path, params)

    return current_path
