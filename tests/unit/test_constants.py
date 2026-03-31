"""
Unit tests for wl_constants module (Layer 0).

Tests verify that all configuration constants, regex patterns, and path helpers
are correctly defined and functional. Coverage target: >= 80%.

These tests ensure that the constants layer remains stable and can be relied upon
by all other wl_manager modules.
"""

import os
import sys
import re
import pytest


# Add bin directory to path to import wl_constants
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'bin'))

import wl_constants


# ═══════════════════════════════════════════════════════════════════════════
# Basic Constant Definition Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_all_constants_defined():
    """Verify all expected constants exist and are not None."""
    expected_constants = [
        'APP_NAME', 'SPLUNK_HOME', 'APPS_DIR', 'OWN_LOOKUPS', 'MAPPING_FILE',
        'MAX_ROWS', 'MAX_COLUMNS', 'MAX_CELL_CHARS', 'MAX_PAYLOAD_BYTES',
        'MAX_AUDIT_VALUE_LINES', 'MAX_DIFF_ROWS', 'MAX_PRESENCE_USERS',
        'MAX_PRESENCE_FILES', 'PRESENCE_TIMEOUT', 'IDLE_TIMEOUT',
        'RATE_WINDOW', 'RATE_MAX_WRITES', 'RATE_MAX_READS',
        'EDIT_ROLES', 'ADMIN_ROLES', 'SUPERADMIN_ROLES', 'EXPIRE_COLUMN_NAMES',
        'AUDIT_INDEX', 'AUDIT_SOURCE', 'AUDIT_SOURCETYPE', 'VERSIONS_DIR',
        'MAX_VERSIONS', 'AUDIT_LOG', 'TRASH_DIR', 'MIN_TRASH_RETENTION_DAYS',
        'DEFAULT_TRASH_RETENTION_DAYS', 'TRASH_CONFIG_FILE', 'DETECTION_RULES_FILE',
        'MAX_DETECTION_RULES', 'MAX_CSVS_PER_RULE', 'MAX_TOTAL_CSV_MAPPINGS',
        'APPROVAL_QUEUE_FILE', 'DAILY_LIMITS_FILE', 'LIMIT_CONFIG_FILE',
        'APPROVAL_EXPIRY_DAYS', 'MAX_PENDING_REQUESTS', 'MAX_RESOLVED_HISTORY',
        'MAX_TRACKED_ANALYSTS', 'NOTIFICATION_FILE', 'MAX_NOTIFICATIONS_PER_USER',
        'NOTIFICATION_MAX_AGE_DAYS', 'DEFAULT_LIMITS', 'DEFAULT_ADMIN_LIMITS',
        'APPROVAL_BULK_ROW_THRESHOLD', 'APPROVAL_BULK_EDIT_THRESHOLD',
        'APPROVAL_COLUMN_NONEMPTY_THRESHOLD', 'APPROVAL_BULK_ADD_THRESHOLD',
        'APPROVAL_REVERT_ROW_THRESHOLD', 'APPROVAL_REVERT_COLUMN_THRESHOLD',
    ]

    for const_name in expected_constants:
        assert hasattr(wl_constants, const_name), f"Missing constant: {const_name}"
        value = getattr(wl_constants, const_name)
        assert value is not None, f"Constant {const_name} is None"


@pytest.mark.unit
def test_app_name():
    """Verify APP_NAME is correctly set."""
    assert wl_constants.APP_NAME == "wl_manager"
    assert isinstance(wl_constants.APP_NAME, str)


@pytest.mark.unit
def test_splunk_home_default():
    """Verify SPLUNK_HOME returns default when env var not set."""
    # The constant is already evaluated at import time, so we check the value
    assert wl_constants.SPLUNK_HOME == "/opt/splunk" or os.environ.get("SPLUNK_HOME")
    assert isinstance(wl_constants.SPLUNK_HOME, str)
    assert len(wl_constants.SPLUNK_HOME) > 0


@pytest.mark.unit
def test_derived_paths_not_none():
    """Verify all derived path constants are defined."""
    paths = [
        wl_constants.APPS_DIR,
        wl_constants.OWN_LOOKUPS,
        wl_constants.MAPPING_FILE,
        wl_constants.AUDIT_LOG,
    ]
    for path in paths:
        assert path is not None
        assert isinstance(path, str)
        assert len(path) > 0


@pytest.mark.unit
def test_paths_are_absolute():
    """Verify derived paths are absolute (start with /)."""
    abs_paths = [
        wl_constants.APPS_DIR,
        wl_constants.OWN_LOOKUPS,
        wl_constants.MAPPING_FILE,
        wl_constants.AUDIT_LOG,
    ]
    for path in abs_paths:
        assert path.startswith('/'), f"Path not absolute: {path}"


# ═══════════════════════════════════════════════════════════════════════════
# Path Helper Function Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_get_splunk_home_function():
    """Verify get_splunk_home() function returns a string."""
    result = wl_constants.get_splunk_home()
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.unit
def test_get_detection_rules_path():
    """Verify get_detection_rules_path() returns correct path."""
    path = wl_constants.get_detection_rules_path()
    assert isinstance(path, str)
    assert "_detection_rules.json" in path
    assert wl_constants.OWN_LOOKUPS in path


@pytest.mark.unit
def test_get_approval_queue_path():
    """Verify get_approval_queue_path() returns correct path."""
    path = wl_constants.get_approval_queue_path()
    assert isinstance(path, str)
    assert "_approval_queue.json" in path
    assert wl_constants.OWN_LOOKUPS in path


# ═══════════════════════════════════════════════════════════════════════════
# Role Sets Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_role_sets_are_sets():
    """Verify all role constants are sets (not lists or tuples)."""
    assert isinstance(wl_constants.EDIT_ROLES, set)
    assert isinstance(wl_constants.ADMIN_ROLES, set)
    assert isinstance(wl_constants.SUPERADMIN_ROLES, set)


@pytest.mark.unit
def test_edit_roles_populated():
    """Verify EDIT_ROLES contains expected roles."""
    assert len(wl_constants.EDIT_ROLES) > 0
    # Check for at least some expected roles
    assert "wl_editor" in wl_constants.EDIT_ROLES or "wl_analyst_editor" in wl_constants.EDIT_ROLES
    assert "admin" in wl_constants.EDIT_ROLES or "sc_admin" in wl_constants.EDIT_ROLES


@pytest.mark.unit
def test_admin_roles_populated():
    """Verify ADMIN_ROLES contains expected roles."""
    assert len(wl_constants.ADMIN_ROLES) > 0
    # Check for at least some expected roles
    assert "admin" in wl_constants.ADMIN_ROLES or "sc_admin" in wl_constants.ADMIN_ROLES or "wl_admin" in wl_constants.ADMIN_ROLES


@pytest.mark.unit
def test_superadmin_roles_populated():
    """Verify SUPERADMIN_ROLES is non-empty."""
    assert len(wl_constants.SUPERADMIN_ROLES) > 0
    assert "wl_superadmin" in wl_constants.SUPERADMIN_ROLES


# ═══════════════════════════════════════════════════════════════════════════
# Limits Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_row_limits_are_positive_integers():
    """Verify row/column limit constants are positive integers."""
    limits = [
        wl_constants.MAX_ROWS,
        wl_constants.MAX_COLUMNS,
        wl_constants.MAX_CELL_CHARS,
    ]
    for limit in limits:
        assert isinstance(limit, int)
        assert limit > 0


@pytest.mark.unit
def test_payload_limits_are_positive_integers():
    """Verify payload limits are positive integers."""
    assert isinstance(wl_constants.MAX_PAYLOAD_BYTES, int)
    assert wl_constants.MAX_PAYLOAD_BYTES > 0
    assert isinstance(wl_constants.MAX_AUDIT_VALUE_LINES, int)
    assert wl_constants.MAX_AUDIT_VALUE_LINES > 0


@pytest.mark.unit
def test_presence_limits_are_positive_integers():
    """Verify presence tracking limits are positive integers."""
    limits = [
        wl_constants.MAX_PRESENCE_USERS,
        wl_constants.MAX_PRESENCE_FILES,
    ]
    for limit in limits:
        assert isinstance(limit, int)
        assert limit > 0


@pytest.mark.unit
def test_timeouts_are_positive_integers():
    """Verify timeout constants are positive integers."""
    assert isinstance(wl_constants.PRESENCE_TIMEOUT, int)
    assert wl_constants.PRESENCE_TIMEOUT > 0
    assert isinstance(wl_constants.IDLE_TIMEOUT, int)
    assert wl_constants.IDLE_TIMEOUT > 0


@pytest.mark.unit
def test_rate_limiting_values():
    """Verify rate limit configuration is correct."""
    assert isinstance(wl_constants.RATE_WINDOW, int)
    assert wl_constants.RATE_WINDOW > 0
    assert isinstance(wl_constants.RATE_MAX_WRITES, int)
    assert wl_constants.RATE_MAX_WRITES > 0
    assert isinstance(wl_constants.RATE_MAX_READS, int)
    assert wl_constants.RATE_MAX_READS > 0
    # Reads should be higher than writes
    assert wl_constants.RATE_MAX_READS >= wl_constants.RATE_MAX_WRITES


@pytest.mark.unit
def test_detection_rules_limits():
    """Verify detection rules limits are positive integers."""
    limits = [
        wl_constants.MAX_DETECTION_RULES,
        wl_constants.MAX_CSVS_PER_RULE,
        wl_constants.MAX_TOTAL_CSV_MAPPINGS,
    ]
    for limit in limits:
        assert isinstance(limit, int)
        assert limit > 0


@pytest.mark.unit
def test_approval_queue_limits():
    """Verify approval queue limits are positive integers."""
    limits = [
        wl_constants.APPROVAL_EXPIRY_DAYS,
        wl_constants.MAX_PENDING_REQUESTS,
        wl_constants.MAX_RESOLVED_HISTORY,
        wl_constants.MAX_TRACKED_ANALYSTS,
    ]
    for limit in limits:
        assert isinstance(limit, int)
        assert limit > 0


@pytest.mark.unit
def test_notification_limits():
    """Verify notification limits are positive integers."""
    assert isinstance(wl_constants.MAX_NOTIFICATIONS_PER_USER, int)
    assert wl_constants.MAX_NOTIFICATIONS_PER_USER > 0
    assert isinstance(wl_constants.NOTIFICATION_MAX_AGE_DAYS, int)
    assert wl_constants.NOTIFICATION_MAX_AGE_DAYS > 0


@pytest.mark.unit
def test_version_control_constants():
    """Verify version control constants."""
    assert isinstance(wl_constants.MAX_VERSIONS, int)
    assert wl_constants.MAX_VERSIONS > 0
    assert isinstance(wl_constants.VERSIONS_DIR, str)
    assert len(wl_constants.VERSIONS_DIR) > 0


# ═══════════════════════════════════════════════════════════════════════════
# Audit Configuration Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_audit_constants():
    """Verify audit configuration constants."""
    assert wl_constants.AUDIT_INDEX == "wl_audit"
    assert wl_constants.AUDIT_SOURCE == "wl_manager"
    assert wl_constants.AUDIT_SOURCETYPE == "wl_audit"
    assert isinstance(wl_constants.AUDIT_INDEX, str)
    assert isinstance(wl_constants.AUDIT_SOURCE, str)
    assert isinstance(wl_constants.AUDIT_SOURCETYPE, str)


# ═══════════════════════════════════════════════════════════════════════════
# Column Names Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_expire_column_names_is_set():
    """Verify EXPIRE_COLUMN_NAMES is a set with expected values."""
    assert isinstance(wl_constants.EXPIRE_COLUMN_NAMES, set)
    assert len(wl_constants.EXPIRE_COLUMN_NAMES) > 0
    # Check for at least some expected column names
    expected_names = {"expires", "expiration", "expiry"}
    assert len(expected_names.intersection(wl_constants.EXPIRE_COLUMN_NAMES)) > 0


# ═══════════════════════════════════════════════════════════════════════════
# Regex Pattern Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_regex_patterns_are_compiled():
    """Verify all regex patterns are compiled regex objects."""
    patterns = [
        wl_constants._CONTROL_CHAR_RE,
        wl_constants._SAFE_COLNAME_RE,
        wl_constants._SANITIZE_RE,
    ]
    for pattern in patterns:
        assert hasattr(pattern, 'search'), "Pattern should have search method"
        assert hasattr(pattern, 'match'), "Pattern should have match method"
        assert isinstance(pattern, type(re.compile('')))


@pytest.mark.unit
def test_control_char_regex():
    """Verify _CONTROL_CHAR_RE works correctly."""
    # Should match control characters
    assert wl_constants._CONTROL_CHAR_RE.search("\x00")
    assert wl_constants._CONTROL_CHAR_RE.search("\x1f")
    assert wl_constants._CONTROL_CHAR_RE.search("\x7f")
    # Should NOT match normal characters
    assert not wl_constants._CONTROL_CHAR_RE.search("A")
    assert not wl_constants._CONTROL_CHAR_RE.search("1")


@pytest.mark.unit
def test_safe_colname_regex():
    """Verify _SAFE_COLNAME_RE validates column names correctly."""
    # Valid column names
    assert wl_constants._SAFE_COLNAME_RE.match("user_id")
    assert wl_constants._SAFE_COLNAME_RE.match("src-ip")
    assert wl_constants._SAFE_COLNAME_RE.match("threshold.value")
    # Invalid column names (no alphanumeric)
    assert not wl_constants._SAFE_COLNAME_RE.match("___")
    assert not wl_constants._SAFE_COLNAME_RE.match("---")


@pytest.mark.unit
def test_sanitize_regex():
    """Verify _SANITIZE_RE removes unwanted characters."""
    test_text = "Hello123!@# <script>"
    # The regex should identify unwanted characters (like < and >)
    matches = wl_constants._SANITIZE_RE.findall(test_text)
    # Check that it finds the < and > characters
    assert len(matches) > 0


# ═══════════════════════════════════════════════════════════════════════════
# Default Limits Configuration Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_default_limits_is_dict():
    """Verify DEFAULT_LIMITS is a dictionary."""
    assert isinstance(wl_constants.DEFAULT_LIMITS, dict)
    assert len(wl_constants.DEFAULT_LIMITS) > 0


@pytest.mark.unit
def test_default_limits_has_expected_keys():
    """Verify DEFAULT_LIMITS contains expected configuration keys."""
    expected_keys = [
        "row_removal", "bulk_row_removal", "row_edit", "bulk_row_edit",
        "reset_frequency", "reset_time_utc",
        "bulk_row_removal_threshold", "bulk_row_edit_threshold",
        "allow_analyst_create_rules", "allow_analyst_create_csv",
    ]
    for key in expected_keys:
        assert key in wl_constants.DEFAULT_LIMITS, f"Missing key in DEFAULT_LIMITS: {key}"


@pytest.mark.unit
def test_default_admin_limits_is_dict():
    """Verify DEFAULT_ADMIN_LIMITS is a dictionary."""
    assert isinstance(wl_constants.DEFAULT_ADMIN_LIMITS, dict)
    assert len(wl_constants.DEFAULT_ADMIN_LIMITS) > 0
    assert "rule_deletion" in wl_constants.DEFAULT_ADMIN_LIMITS
    assert "csv_deletion" in wl_constants.DEFAULT_ADMIN_LIMITS


# ═══════════════════════════════════════════════════════════════════════════
# Fallback Threshold Constants Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_fallback_thresholds_are_positive_integers():
    """Verify fallback approval thresholds are positive integers."""
    thresholds = [
        wl_constants.APPROVAL_BULK_ROW_THRESHOLD,
        wl_constants.APPROVAL_BULK_EDIT_THRESHOLD,
        wl_constants.APPROVAL_COLUMN_NONEMPTY_THRESHOLD,
        wl_constants.APPROVAL_BULK_ADD_THRESHOLD,
        wl_constants.APPROVAL_REVERT_ROW_THRESHOLD,
        wl_constants.APPROVAL_REVERT_COLUMN_THRESHOLD,
    ]
    for threshold in thresholds:
        assert isinstance(threshold, int)
        assert threshold > 0


# ═══════════════════════════════════════════════════════════════════════════
# Module API Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_module_has_all_list():
    """Verify module has __all__ list with public API."""
    assert hasattr(wl_constants, '__all__')
    assert isinstance(wl_constants.__all__, list)
    assert len(wl_constants.__all__) > 0
    # Check that some key exports are in __all__
    assert 'APP_NAME' in wl_constants.__all__
    assert 'MAX_ROWS' in wl_constants.__all__
    assert 'EDIT_ROLES' in wl_constants.__all__


@pytest.mark.unit
def test_trash_retention_constants():
    """Verify trash retention configuration."""
    assert isinstance(wl_constants.MIN_TRASH_RETENTION_DAYS, int)
    assert wl_constants.MIN_TRASH_RETENTION_DAYS > 0
    assert isinstance(wl_constants.DEFAULT_TRASH_RETENTION_DAYS, int)
    assert wl_constants.DEFAULT_TRASH_RETENTION_DAYS > 0
    # Default should be >= minimum
    assert wl_constants.DEFAULT_TRASH_RETENTION_DAYS >= wl_constants.MIN_TRASH_RETENTION_DAYS
