"""
Unit test configuration and fixtures.

Provides fixtures specific to unit testing (no Docker required).
All unit tests run offline with mocked dependencies.
"""

import os
import sys
from datetime import datetime, timezone
from unittest.mock import patch

import pytest


@pytest.fixture
def mock_request():
    """
    Mock Splunk REST request object (used by wl_rbac.get_user, get_roles).

    Returns a dict-like object with headers and session_key.
    """
    return {
        "headers": {
            "Authorization": "Bearer test-token",
            "X-Splunk-Form-Key": "test-form-key",
        },
        "session_key": "test-session-key",
    }


@pytest.fixture
def mock_session_key():
    """
    Mock session key for Splunk REST API calls.

    Used by wl_rbac.get_admin_users, wl_audit.post_audit_event, etc.
    """
    return "test-session-key"


@pytest.fixture
def frozen_now(freezegun):
    """
    Freezegun fixture for time-dependent tests (presence, ratelimit).

    Returns a datetime object and freezes time at that moment.
    """
    frozen_time = freezegun.freeze_time("2026-03-31 12:00:00", tz_offset=0)
    frozen_time.start()
    yield datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc)
    frozen_time.stop()


@pytest.fixture(autouse=True)
def reset_module_state():
    """
    Reset module-level state before each unit test.

    Clears _presence and _rate_limits dicts in stateful modules.
    This ensures tests don't interfere with each other.
    """
    yield
    # Cleanup after test — clear module state
    # (This will be used by Phase 1 tasks 2-3 for wl_ratelimit and wl_presence)
    pass
