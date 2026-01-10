"""Shared pytest fixtures for integration tests."""

from __future__ import annotations

import sys
from collections.abc import Generator
from pathlib import Path

import pytest


@pytest.fixture
def temp_migrations_module(tmp_path: Path) -> Generator[tuple[str, Path], None, None]:
    """Create a temporary Python package for migrations.

    Yields:
        Tuple of (module_name, package_path) for the temporary migrations package.

    The fixture handles sys.path and sys.modules cleanup automatically.
    """
    pkg_name = "test_api_migrations"
    pkg_path = tmp_path / pkg_name
    pkg_path.mkdir()
    (pkg_path / "__init__.py").write_text("")

    # Add to sys.path for import
    sys.path.insert(0, str(tmp_path))

    yield pkg_name, pkg_path

    # Cleanup: remove from sys.path
    if str(tmp_path) in sys.path:
        sys.path.remove(str(tmp_path))

    # Cleanup: remove imported modules to avoid cross-test pollution
    modules_to_remove = [key for key in sys.modules if key.startswith(pkg_name)]
    for mod in modules_to_remove:
        del sys.modules[mod]
