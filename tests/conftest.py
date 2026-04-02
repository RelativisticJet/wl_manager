"""
Global pytest configuration and fixtures.

Sets up:
- PYTHONPATH to include stubs/ directory (for mocking Splunk SDK)
- Docker fixture for integration tests (optional)
- Temporary directory fixtures for file I/O tests
"""

import os
import sys
import tempfile
import shutil
import subprocess
from pathlib import Path

import pytest


# Add stubs/ to PYTHONPATH so tests can "import splunk.rest" and get the mock
TESTS_DIR = Path(__file__).parent
STUBS_DIR = TESTS_DIR / "stubs"
if str(STUBS_DIR) not in sys.path:
    sys.path.insert(0, str(STUBS_DIR))


@pytest.fixture(scope="session")
def docker_service():
    """
    Optional Docker fixture for integration tests.

    Returns a dict with Docker service status and methods.
    If Docker or container is unavailable, returns a "disabled" state.

    Integration tests check this fixture to decide whether to run.
    """
    container_name = "wl_manager_test"

    def is_running():
        try:
            result = subprocess.run(
                ["docker", "inspect", container_name],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def start():
        """Start the Docker container (assumes it was previously created with docker-compose)."""
        try:
            subprocess.run(
                ["docker", "start", container_name],
                capture_output=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    def stop():
        """Stop the Docker container."""
        try:
            subprocess.run(
                ["docker", "stop", container_name],
                capture_output=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    running = is_running()
    if not running:
        start()
        running = is_running()

    return {
        "enabled": running,
        "container_name": container_name,
        "is_running": is_running,
        "start": start,
        "stop": stop,
    }


@pytest.fixture(scope="function")
def tmp_lookups(tmp_path):
    """
    Temporary lookups directory for CSV file I/O tests.

    Scope: function (new temp dir per test)

    Returns the path to a temporary directory that mimics the wl_manager/lookups/ layout.
    Used by: wl_csv tests, wl_versions tests, wl_rules tests
    """
    lookups_dir = tmp_path / "lookups"
    lookups_dir.mkdir()
    return lookups_dir


@pytest.fixture(scope="function")
def mock_splunk_home(monkeypatch, tmp_path):
    """
    Mock SPLUNK_HOME environment variable for tests.

    Scope: function (new environment per test)

    Returns the path and patches os.environ["SPLUNK_HOME"] to point to it.
    Creates the directory structure: SPLUNK_HOME/etc/apps/wl_manager/lookups
    Used by: integration tests, file path resolution tests
    """
    mock_home = tmp_path / "splunk_home"
    mock_home.mkdir()

    # Create the directory structure
    apps_dir = mock_home / "etc" / "apps" / "wl_manager" / "lookups"
    apps_dir.mkdir(parents=True)

    # Patch the environment
    monkeypatch.setenv("SPLUNK_HOME", str(mock_home))

    return mock_home
