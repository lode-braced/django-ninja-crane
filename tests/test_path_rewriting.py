"""Tests for path rewriting utilities."""

from pathlib import Path

from crane.api_version import PathOperation
from crane.data_migrations import DataMigrationSet, PathRewrite
from crane.delta import HttpMethod, OperationAdded, OperationRemoved, VersionDelta
from crane.migrations_generator import LoadedMigration, _detect_path_renames
from crane.path_rewriting import (
    build_path,
    get_path_rewrites_for_upgrade,
    match_path_pattern,
    rewrite_path,
)


class TestMatchPathPattern:
    def test_simple_match(self):
        result = match_path_pattern("/users", "/users")
        assert result == {}

    def test_single_param(self):
        result = match_path_pattern("/users/{id}", "/users/123")
        assert result == {"id": "123"}

    def test_multiple_params(self):
        result = match_path_pattern("/users/{user_id}/posts/{post_id}", "/users/1/posts/42")
        assert result == {"user_id": "1", "post_id": "42"}

    def test_no_match_different_path(self):
        result = match_path_pattern("/users/{id}", "/posts/123")
        assert result is None

    def test_no_match_extra_segments(self):
        result = match_path_pattern("/users/{id}", "/users/123/extra")
        assert result is None

    def test_no_match_missing_segments(self):
        result = match_path_pattern("/users/{id}/posts", "/users/123")
        assert result is None

    def test_param_with_special_chars(self):
        result = match_path_pattern("/files/{path}", "/files/my-file_v2.txt")
        assert result == {"path": "my-file_v2.txt"}


class TestBuildPath:
    def test_simple_path(self):
        result = build_path("/users", {})
        assert result == "/users"

    def test_single_param(self):
        result = build_path("/people/{id}", {"id": "123"})
        assert result == "/people/123"

    def test_multiple_params(self):
        result = build_path("/users/{user_id}/posts/{post_id}", {"user_id": "1", "post_id": "42"})
        assert result == "/users/1/posts/42"

    def test_extra_params_ignored(self):
        result = build_path("/users/{id}", {"id": "123", "extra": "ignored"})
        assert result == "/users/123"

    def test_missing_param_left_as_placeholder(self):
        result = build_path("/users/{id}", {})
        assert result == "/users/{id}"


class TestRewritePath:
    def test_no_rewrites(self):
        result = rewrite_path("/users/123", "get", [])
        assert result == "/users/123"

    def test_simple_rewrite(self):
        rewrites = [
            PathRewrite(old_path="/persons/{id}", new_path="/people/{id}"),
        ]
        result = rewrite_path("/persons/123", "get", rewrites)
        assert result == "/people/123"

    def test_no_match_returns_original(self):
        rewrites = [
            PathRewrite(old_path="/persons/{id}", new_path="/people/{id}"),
        ]
        result = rewrite_path("/users/123", "get", rewrites)
        assert result == "/users/123"

    def test_method_filter_matches(self):
        rewrites = [
            PathRewrite(old_path="/persons/{id}", new_path="/people/{id}", methods=["get", "put"]),
        ]
        result = rewrite_path("/persons/123", "get", rewrites)
        assert result == "/people/123"

    def test_method_filter_no_match(self):
        rewrites = [
            PathRewrite(old_path="/persons/{id}", new_path="/people/{id}", methods=["post"]),
        ]
        result = rewrite_path("/persons/123", "get", rewrites)
        assert result == "/persons/123"

    def test_chained_rewrites(self):
        # v1: /persons/{id} -> v2: /people/{id} -> v3: /users/{id}
        rewrites = [
            PathRewrite(old_path="/persons/{id}", new_path="/people/{id}"),
            PathRewrite(old_path="/people/{id}", new_path="/users/{id}"),
        ]
        result = rewrite_path("/persons/123", "get", rewrites)
        assert result == "/users/123"

    def test_param_rename(self):
        rewrites = [
            PathRewrite(old_path="/users/{user_id}", new_path="/users/{id}"),
        ]
        # This extracts user_id=123, but new path uses {id}, so it stays as placeholder
        # unless we handle param mapping - for now this is expected behavior
        result = rewrite_path("/users/123", "get", rewrites)
        # The match extracts {"user_id": "123"}, build_path uses {id} which isn't in params
        assert result == "/users/{id}"


def make_migration(
    sequence: int,
    from_version: str | None,
    to_version: str,
    path_rewrites: list[PathRewrite] | None = None,
) -> LoadedMigration:
    """Helper to create test migrations."""
    data_migs = None
    if path_rewrites:
        data_migs = DataMigrationSet(path_rewrites=path_rewrites)

    return LoadedMigration(
        sequence=sequence,
        slug=f"m{sequence}",
        file_path=Path(f"m_{sequence:04d}_m{sequence}.py"),
        dependencies=[],
        from_version=from_version,
        to_version=to_version,
        delta=VersionDelta(actions=[]),
        data_migrations=data_migs,
    )


class TestGetPathRewritesForUpgrade:
    def test_same_version_returns_empty(self):
        migrations = [make_migration(1, None, "v1")]
        result = get_path_rewrites_for_upgrade(migrations, "v1", "v1")
        assert result == []

    def test_no_rewrites_defined(self):
        migrations = [
            make_migration(1, None, "v1"),
            make_migration(2, "v1", "v2"),
        ]
        result = get_path_rewrites_for_upgrade(migrations, "v1", "v2")
        assert result == []

    def test_collects_rewrites_from_migration(self):
        rewrites = [PathRewrite(old_path="/persons/{id}", new_path="/people/{id}")]
        migrations = [
            make_migration(1, None, "v1"),
            make_migration(2, "v1", "v2", path_rewrites=rewrites),
        ]
        result = get_path_rewrites_for_upgrade(migrations, "v1", "v2")
        assert len(result) == 1
        assert result[0].old_path == "/persons/{id}"

    def test_collects_rewrites_across_multiple_versions(self):
        migrations = [
            make_migration(1, None, "v1"),
            make_migration(
                2,
                "v1",
                "v2",
                path_rewrites=[PathRewrite(old_path="/persons/{id}", new_path="/people/{id}")],
            ),
            make_migration(
                3,
                "v2",
                "v3",
                path_rewrites=[PathRewrite(old_path="/people/{id}", new_path="/users/{id}")],
            ),
        ]
        result = get_path_rewrites_for_upgrade(migrations, "v1", "v3")
        assert len(result) == 2
        assert result[0].old_path == "/persons/{id}"
        assert result[1].old_path == "/people/{id}"

    def test_downgrade_returns_empty(self):
        migrations = [
            make_migration(1, None, "v1"),
            make_migration(
                2,
                "v1",
                "v2",
                path_rewrites=[PathRewrite(old_path="/persons/{id}", new_path="/people/{id}")],
            ),
        ]
        # Downgrade direction - no path rewriting needed for requests
        result = get_path_rewrites_for_upgrade(migrations, "v2", "v1")
        assert result == []

    def test_unknown_version_returns_empty(self):
        migrations = [make_migration(1, None, "v1")]
        result = get_path_rewrites_for_upgrade(migrations, "v1", "v99")
        assert result == []


def make_operation(
    method: HttpMethod = "get",
    path: str = "/test",
    operation_id: str = "test_op",
) -> PathOperation:
    """Helper to create test operations."""
    return PathOperation(
        method=method,
        path=path,
        query_params={},
        path_params={},
        cookie_params={},
        request_body_schema=[],
        response_bodies=[],
        operation_id=operation_id,
        openapi_json={},
    )


class TestDetectPathRenames:
    def test_no_renames_when_no_operations(self):
        delta = VersionDelta(actions=[])
        result = _detect_path_renames(delta)
        assert result == []

    def test_no_renames_when_only_added(self):
        delta = VersionDelta(
            actions=[
                OperationAdded(
                    path="/users",
                    method="get",
                    new_operation=make_operation(path="/users", operation_id="list_users"),
                ),
            ]
        )
        result = _detect_path_renames(delta)
        assert result == []

    def test_no_renames_when_only_removed(self):
        delta = VersionDelta(
            actions=[
                OperationRemoved(
                    path="/users",
                    method="get",
                    old_operation=make_operation(path="/users", operation_id="list_users"),
                ),
            ]
        )
        result = _detect_path_renames(delta)
        assert result == []

    def test_detects_rename_by_operation_id(self):
        """When operation_id matches but path differs, it's a rename."""
        delta = VersionDelta(
            actions=[
                OperationRemoved(
                    path="/persons/{id}",
                    method="get",
                    old_operation=make_operation(path="/persons/{id}", operation_id="get_person"),
                ),
                OperationAdded(
                    path="/people/{id}",
                    method="get",
                    new_operation=make_operation(path="/people/{id}", operation_id="get_person"),
                ),
            ]
        )
        result = _detect_path_renames(delta)
        assert len(result) == 1
        assert result[0] == ("/persons/{id}", "/people/{id}", "get")

    def test_no_rename_when_operation_id_differs(self):
        """Different operation_id means it's not a rename."""
        delta = VersionDelta(
            actions=[
                OperationRemoved(
                    path="/persons/{id}",
                    method="get",
                    old_operation=make_operation(path="/persons/{id}", operation_id="get_person"),
                ),
                OperationAdded(
                    path="/people/{id}",
                    method="get",
                    new_operation=make_operation(
                        path="/people/{id}",
                        operation_id="get_user",  # Different!
                    ),
                ),
            ]
        )
        result = _detect_path_renames(delta)
        assert result == []

    def test_no_rename_when_method_differs(self):
        """Same operation_id but different method is not a rename."""
        delta = VersionDelta(
            actions=[
                OperationRemoved(
                    path="/persons/{id}",
                    method="get",
                    old_operation=make_operation(path="/persons/{id}", operation_id="person_op"),
                ),
                OperationAdded(
                    path="/people/{id}",
                    method="post",  # Different method
                    new_operation=make_operation(path="/people/{id}", operation_id="person_op"),
                ),
            ]
        )
        result = _detect_path_renames(delta)
        assert result == []

    def test_detects_multiple_renames(self):
        """Can detect multiple path renames in one migration."""
        delta = VersionDelta(
            actions=[
                OperationRemoved(
                    path="/persons",
                    method="get",
                    old_operation=make_operation(path="/persons", operation_id="list_persons"),
                ),
                OperationRemoved(
                    path="/persons/{id}",
                    method="get",
                    old_operation=make_operation(path="/persons/{id}", operation_id="get_person"),
                ),
                OperationAdded(
                    path="/people",
                    method="get",
                    new_operation=make_operation(path="/people", operation_id="list_persons"),
                ),
                OperationAdded(
                    path="/people/{id}",
                    method="get",
                    new_operation=make_operation(path="/people/{id}", operation_id="get_person"),
                ),
            ]
        )
        result = _detect_path_renames(delta)
        assert len(result) == 2
        # Convert to set for order-independent comparison
        result_set = {(old, new, method) for old, new, method in result}
        assert result_set == {
            ("/persons", "/people", "get"),
            ("/persons/{id}", "/people/{id}", "get"),
        }
