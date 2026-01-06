import sys
from pathlib import Path
from textwrap import dedent

import pytest
from ninja import NinjaAPI, Router

from crane.api_version import ApiVersion, PathOperation
from crane.delta import VersionDelta, create_delta
from crane.migrations_generator import (
    LoadedMigration,
    MigrationChainError,
    MigrationLoadError,
    _get_next_sequence,
    _parse_migration_filename,
    _slugify,
    detect_changes,
    generate_migration,
    get_known_api_state,
    load_migrations,
    render_migration_file,
)


# === Helper Functions Tests ===


class TestParseMigrationFilename:
    def test_valid_filename(self):
        assert _parse_migration_filename("m_0001_initial.py") == (1, "initial")

    def test_valid_with_underscores(self):
        assert _parse_migration_filename("m_0023_add_user_endpoint.py") == (
            23,
            "add_user_endpoint",
        )

    def test_high_sequence_number(self):
        assert _parse_migration_filename("m_9999_final.py") == (9999, "final")

    def test_invalid_prefix(self):
        assert _parse_migration_filename("migration_0001_foo.py") is None

    def test_invalid_sequence_not_four_digits(self):
        assert _parse_migration_filename("m_01_foo.py") is None

    def test_invalid_sequence_non_numeric(self):
        assert _parse_migration_filename("m_abcd_foo.py") is None

    def test_invalid_extension(self):
        assert _parse_migration_filename("m_0001_initial.txt") is None

    def test_missing_slug(self):
        assert _parse_migration_filename("m_0001_.py") is None


class TestSlugify:
    def test_spaces_to_underscores(self):
        assert _slugify("Add Users Endpoint") == "add_users_endpoint"

    def test_hyphens_to_underscores(self):
        assert _slugify("add-users-endpoint") == "add_users_endpoint"

    def test_special_chars_removed(self):
        assert _slugify("v2.0-release!") == "v20_release"

    def test_collapse_multiple_underscores(self):
        assert _slugify("add   users") == "add_users"

    def test_strip_leading_trailing_underscores(self):
        assert _slugify("_test_") == "test"

    def test_empty_after_processing_returns_default(self):
        assert _slugify("!!!") == "migration"

    def test_already_valid(self):
        assert _slugify("initial") == "initial"

    def test_truncates_long_description(self):
        long_desc = "This is a very long description that exceeds the maximum length"
        result = _slugify(long_desc)
        assert len(result) <= 50

    def test_truncates_at_word_boundary(self):
        # "add_new_endpoint_for_users" is 26 chars, truncating at 20 should give "add_new_endpoint"
        result = _slugify("add new endpoint for users", max_length=20)
        assert result == "add_new_endpoint"
        assert "_for" not in result  # Should not cut mid-word

    def test_truncates_without_word_boundary_if_needed(self):
        # If no underscore in second half, just truncate
        result = _slugify("abcdefghijklmnopqrstuvwxyz", max_length=10)
        assert len(result) <= 10

    def test_custom_max_length(self):
        result = _slugify("one two three four five", max_length=15)
        assert len(result) <= 15


class TestGetNextSequence:
    def test_empty_migrations_returns_one(self):
        assert _get_next_sequence([]) == 1

    def test_single_migration_returns_next(self):
        m = LoadedMigration(
            sequence=1,
            slug="initial",
            file_path=Path("m_0001_initial.py"),
            dependencies=[],
            from_version=None,
            to_version="v1",
            delta=VersionDelta(actions=[]),
        )
        assert _get_next_sequence([m]) == 2

    def test_multiple_migrations_returns_max_plus_one(self):
        migrations = [
            LoadedMigration(
                sequence=i,
                slug=f"m{i}",
                file_path=Path(f"m_{i:04d}_m{i}.py"),
                dependencies=[],
                from_version=None,
                to_version=f"v{i}",
                delta=VersionDelta(actions=[]),
            )
            for i in [1, 3, 5]
        ]
        assert _get_next_sequence(migrations) == 6


# === Migration Loading Tests ===


class TestLoadMigrations:
    def test_nonexistent_module_returns_empty(self):
        result = load_migrations("nonexistent.module.that.does.not.exist")
        assert result == []

    def test_loads_migrations_from_module(self, tmp_path):
        migrations_dir = tmp_path / "test_migrations"
        migrations_dir.mkdir()
        (migrations_dir / "__init__.py").write_text("")

        # Create a valid migration file
        migration_content = dedent("""
            from crane.delta import VersionDelta

            dependencies = []
            from_version = None
            to_version = "initial"
            delta = VersionDelta(actions=[])
        """)
        (migrations_dir / "m_0001_initial.py").write_text(migration_content)

        # Add to sys.path temporarily
        sys.path.insert(0, str(tmp_path))
        try:
            result = load_migrations("test_migrations")
            assert len(result) == 1
            assert result[0].sequence == 1
            assert result[0].slug == "initial"
            assert result[0].to_version == "initial"
            assert result[0].from_version is None
            assert result[0].dependencies == []
        finally:
            sys.path.remove(str(tmp_path))
            # Clean up module cache
            if "test_migrations" in sys.modules:
                del sys.modules["test_migrations"]
            if "test_migrations.m_0001_initial" in sys.modules:
                del sys.modules["test_migrations.m_0001_initial"]

    def test_loads_multiple_migrations_in_order(self, tmp_path):
        migrations_dir = tmp_path / "test_migrations_multi"
        migrations_dir.mkdir()
        (migrations_dir / "__init__.py").write_text("")

        # Create migrations out of order
        for seq, version in [(3, "third"), (1, "first"), (2, "second")]:
            content = dedent(f"""
                from crane.delta import VersionDelta

                dependencies = []
                from_version = None
                to_version = "{version}"
                delta = VersionDelta(actions=[])
            """)
            (migrations_dir / f"m_{seq:04d}_{version}.py").write_text(content)

        sys.path.insert(0, str(tmp_path))
        try:
            result = load_migrations("test_migrations_multi")
            assert len(result) == 3
            assert [m.sequence for m in result] == [1, 2, 3]
            assert [m.to_version for m in result] == ["first", "second", "third"]
        finally:
            sys.path.remove(str(tmp_path))
            # Clean up module cache
            for key in list(sys.modules.keys()):
                if key.startswith("test_migrations_multi"):
                    del sys.modules[key]

    def test_missing_to_version_raises_error(self, tmp_path):
        migrations_dir = tmp_path / "test_migrations_invalid"
        migrations_dir.mkdir()
        (migrations_dir / "__init__.py").write_text("")

        content = dedent("""
            from crane.delta import VersionDelta

            dependencies = []
            from_version = None
            # to_version is missing!
            delta = VersionDelta(actions=[])
        """)
        (migrations_dir / "m_0001_bad.py").write_text(content)

        sys.path.insert(0, str(tmp_path))
        try:
            with pytest.raises(MigrationLoadError, match="missing required 'to_version'"):
                load_migrations("test_migrations_invalid")
        finally:
            sys.path.remove(str(tmp_path))
            for key in list(sys.modules.keys()):
                if key.startswith("test_migrations_invalid"):
                    del sys.modules[key]


class TestValidateChain:
    def test_valid_chain_passes(self, tmp_path):
        migrations_dir = tmp_path / "test_chain_valid"
        migrations_dir.mkdir()
        (migrations_dir / "__init__.py").write_text("")

        # First migration with no dependencies
        m1 = dedent("""
            from crane.delta import VersionDelta

            dependencies = []
            from_version = None
            to_version = "v1"
            delta = VersionDelta(actions=[])
        """)
        (migrations_dir / "m_0001_v1.py").write_text(m1)

        # Second migration depends on first
        m2 = dedent("""
            from crane.delta import VersionDelta

            dependencies = [("test_chain_valid", "v1")]
            from_version = "v1"
            to_version = "v2"
            delta = VersionDelta(actions=[])
        """)
        (migrations_dir / "m_0002_v2.py").write_text(m2)

        sys.path.insert(0, str(tmp_path))
        try:
            result = load_migrations("test_chain_valid")
            assert len(result) == 2
        finally:
            sys.path.remove(str(tmp_path))
            for key in list(sys.modules.keys()):
                if key.startswith("test_chain_valid"):
                    del sys.modules[key]

    def test_broken_chain_raises_error(self, tmp_path):
        migrations_dir = tmp_path / "test_chain_broken"
        migrations_dir.mkdir()
        (migrations_dir / "__init__.py").write_text("")

        # Migration that depends on non-existent version
        content = dedent("""
            from crane.delta import VersionDelta

            dependencies = [("test_chain_broken", "nonexistent")]
            from_version = None
            to_version = "v1"
            delta = VersionDelta(actions=[])
        """)
        (migrations_dir / "m_0001_v1.py").write_text(content)

        sys.path.insert(0, str(tmp_path))
        try:
            with pytest.raises(MigrationChainError, match="not available"):
                load_migrations("test_chain_broken")
        finally:
            sys.path.remove(str(tmp_path))
            for key in list(sys.modules.keys()):
                if key.startswith("test_chain_broken"):
                    del sys.modules[key]


# === State Reconstruction Tests ===


class TestGetKnownApiState:
    def test_empty_migrations_returns_empty_state(self):
        result = get_known_api_state([])
        assert result.path_operations == {}
        assert result.schema_definitions == {}

    def test_applies_migrations_forwards(self):
        from crane.delta import OperationAdded

        op = PathOperation(
            method="get",
            path="/users",
            query_params={},
            path_params={},
            cookie_params={},
            request_body_schema=[],
            response_bodies=[],
            operation_id="list_users",
            openapi_json={"operationId": "list_users"},
        )
        delta = VersionDelta(
            actions=[OperationAdded(path="/users", method="get", new_operation=op)]
        )
        m = LoadedMigration(
            sequence=1,
            slug="initial",
            file_path=Path("m_0001_initial.py"),
            dependencies=[],
            from_version=None,
            to_version="v1",
            delta=delta,
        )

        result = get_known_api_state([m])

        assert "/users" in result.path_operations
        assert len(result.path_operations["/users"]) == 1
        assert result.path_operations["/users"][0].operation_id == "list_users"


# === Migration File Rendering Tests ===


class TestRenderMigrationFile:
    def test_renders_initial_migration(self):
        delta = VersionDelta(actions=[])
        content = render_migration_file([], None, "v1", "Initial API version", delta)

        assert "from crane.delta import VersionDelta" in content
        assert "dependencies: list[tuple[str, str]] = []" in content
        assert "from_version: str | None = None" in content
        assert "to_version: str = 'v1'" in content
        assert "Initial API version" in content
        assert "delta = VersionDelta.model_validate_json(" in content

    def test_renders_migration_with_dependencies(self):
        delta = VersionDelta(actions=[])
        deps = [("myapp.migrations", "v1")]
        content = render_migration_file(deps, "v1", "v2", "Add users endpoint", delta)

        assert "[('myapp.migrations', 'v1')]" in content
        assert "from_version: str | None = 'v1'" in content
        assert "to_version: str = 'v2'" in content
        assert "Add users endpoint" in content

    def test_rendered_file_is_valid_python(self):
        delta = VersionDelta(actions=[])
        content = render_migration_file([], None, "v1", "Initial version", delta)

        # Should not raise SyntaxError
        compile(content, "<string>", "exec")


# === Change Detection Tests ===


class TestDetectChanges:
    def test_no_changes_returns_none(self, tmp_path):
        api = NinjaAPI()

        @api.get("/test")
        def test_endpoint():
            return {"status": "ok"}

        # Create migrations that match current state
        from crane.api_version import create_api_version

        current = create_api_version(api)
        delta = create_delta(ApiVersion(path_operations={}, schema_definitions={}), current)

        migrations_dir = tmp_path / "test_detect_no_change"
        migrations_dir.mkdir()
        (migrations_dir / "__init__.py").write_text("")

        # Create migration that produces current state
        content = render_migration_file([], None, "v1", "Initial version", delta)
        (migrations_dir / "m_0001_initial.py").write_text(content)

        sys.path.insert(0, str(tmp_path))
        try:
            result = detect_changes(api, "test_detect_no_change")
            assert result is None
        finally:
            sys.path.remove(str(tmp_path))
            for key in list(sys.modules.keys()):
                if key.startswith("test_detect_no_change"):
                    del sys.modules[key]

    def test_changes_detected_returns_delta(self):
        api = NinjaAPI()

        @api.get("/test")
        def test_endpoint():
            return {"status": "ok"}

        # No migrations exist, so any API endpoints are new
        result = detect_changes(api, "nonexistent.module")

        assert result is not None
        assert len(result.actions) > 0


# === Migration Generation Tests ===


class TestGenerateMigration:
    def test_generates_initial_migration(self, tmp_path):
        api = NinjaAPI()
        router = Router()

        @router.get("/items")
        def list_items():
            return []

        api.add_router("/", router)

        migrations_dir = tmp_path / "gen_initial"
        migrations_dir.mkdir()

        sys.path.insert(0, str(tmp_path))
        try:
            # Need to create __init__.py for module import to work
            (migrations_dir / "__init__.py").write_text("")

            result = generate_migration(api, "gen_initial", "v1", "Initial API version")

            assert result is not None
            assert result.name == "m_0001_initial_api_version.py"
            assert result.exists()

            # Verify content
            content = result.read_text()
            assert "dependencies: list[tuple[str, str]] = []" in content
            assert "from_version: str | None = None" in content
            assert "to_version: str = 'v1'" in content
            assert "Initial API version" in content
        finally:
            sys.path.remove(str(tmp_path))
            for key in list(sys.modules.keys()):
                if key.startswith("gen_initial"):
                    del sys.modules[key]

    def test_generates_subsequent_migration_with_dependencies(self, tmp_path):
        api = NinjaAPI()
        router = Router()

        @router.get("/items")
        def list_items():
            return []

        api.add_router("/", router)

        migrations_dir = tmp_path / "gen_subsequent"
        migrations_dir.mkdir()
        (migrations_dir / "__init__.py").write_text("")

        sys.path.insert(0, str(tmp_path))
        try:
            # Generate first migration
            result1 = generate_migration(api, "gen_subsequent", "v1", "Initial version")
            assert result1 is not None

            # Add another endpoint
            @router.post("/items")
            def create_item():
                return {}

            # Generate second migration
            result2 = generate_migration(api, "gen_subsequent", "v2", "Add create item endpoint")
            assert result2 is not None
            assert result2.name == "m_0002_add_create_item_endpoint.py"

            content = result2.read_text()
            assert "[('gen_subsequent', 'v1')]" in content
            assert "from_version: str | None = 'v1'" in content
            assert "to_version: str = 'v2'" in content
            assert "Add create item endpoint" in content
        finally:
            sys.path.remove(str(tmp_path))
            for key in list(sys.modules.keys()):
                if key.startswith("gen_subsequent"):
                    del sys.modules[key]

    def test_no_changes_returns_none(self, tmp_path):
        api = NinjaAPI()
        router = Router()

        @router.get("/items")
        def list_items():
            return []

        api.add_router("/", router)

        migrations_dir = tmp_path / "gen_no_change"
        migrations_dir.mkdir()
        (migrations_dir / "__init__.py").write_text("")

        sys.path.insert(0, str(tmp_path))
        try:
            # Generate first migration
            result1 = generate_migration(api, "gen_no_change", "v1", "Initial version")
            assert result1 is not None

            # Try to generate again without changes
            result2 = generate_migration(api, "gen_no_change", "v2", "No changes")
            assert result2 is None
        finally:
            sys.path.remove(str(tmp_path))
            for key in list(sys.modules.keys()):
                if key.startswith("gen_no_change"):
                    del sys.modules[key]
