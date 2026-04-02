"""
Unit test configuration and fixtures.

Provides fixtures specific to unit testing (no Docker required).
All unit tests run offline with mocked dependencies.

Fixture hierarchy:
- Global fixtures (tests/conftest.py): session-scoped Docker, temp dirs, PYTHONPATH setup
- Unit fixtures (tests/unit/conftest.py): function-scoped mocks, Splunk SDK stubs, state resets
"""

import os
import sys
from datetime import datetime, timezone
from unittest.mock import patch

import pytest


@pytest.fixture(scope="function")
def mock_request():
    """
    Mock Splunk REST request object (used by wl_rbac.get_user, get_roles).

    Scope: function

    Returns a dict-like object with headers and session_key.
    Used by: RBAC tests, handler tests
    """
    return {
        "headers": {
            "Authorization": "Bearer test-token",
            "X-Splunk-Form-Key": "test-form-key",
        },
        "session_key": "test-session-key",
    }


@pytest.fixture(scope="function")
def mock_session_key():
    """
    Mock session key for Splunk REST API calls.

    Scope: function

    Used by wl_rbac.get_admin_users, wl_audit.post_audit_event, etc.
    """
    return "test-session-key"


@pytest.fixture(scope="function")
def frozen_now(freezegun):
    """
    Freezegun fixture for time-dependent tests (presence, ratelimit).

    Scope: function
    Freezes time at: 2026-03-31 12:00:00 UTC

    Returns a datetime object and freezes time at that moment.
    Used by: presence tests, ratelimit tests, time-dependent state tests
    """
    frozen_time = freezegun.freeze_time("2026-03-31 12:00:00", tz_offset=0)
    frozen_time.start()
    yield datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc)
    frozen_time.stop()


@pytest.fixture(scope="function", autouse=True)
def reset_module_state():
    """
    Reset module-level state before each unit test (autouse).

    Scope: function
    Autouse: True (runs for every test automatically)

    Clears _presence and _rate_limits dicts in stateful modules.
    This ensures tests don't interfere with each other.
    Note: Currently a placeholder — will be extended in Phase 7 for state cleanup.
    """
    yield
    # Cleanup after test — clear module state
    # (This will be used by Phase 1 tasks 2-3 for wl_ratelimit and wl_presence)
    pass
