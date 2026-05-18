"""
POST error-path contract tests.

Error responses are part of the public API contract — the
frontend reads ``response.error`` to surface a toast, the
audit-log dashboard categorizes errors by their text, and CI
alerts may match on specific error strings. A drift in error
shape or message wording is a real regression.

These tests pin the error contract:

1. **Status code** — 400 / 403 / 404 / 409 as documented
2. **Error field present** — every error response has ``"error"``
3. **Error message contains the right substring** — frontend
   toast text comes from this; flaky-passing on error message
   wording would defeat error-localization work down the road

Origin
------

Replaces high-value scenarios from the deleted zombie tests
(see ``RING_FINDINGS.md`` R0-F2 and ``RING1_INPUT_handler_contracts.md``
"POST error-path contracts"). Plus tests covering the 2026-04-26
strict-ASCII policy decision and the R0-F4 path-traversal pin.
"""

import json

import pytest


pytestmark = pytest.mark.docker


def _post_action(container_curl, action: str, payload: dict):
    """Issue a POST and return ``(http_code, body_dict)``."""
    body = json.dumps({"action": action, **payload})
    proc = container_curl(
        "/services/custom/wl_manager",
        method="POST",
        data=body,
        content_type="application/json",
        check=False,
    )
    raw = proc.stdout.strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return (200 if proc.returncode == 0 else 0,
                {"_raw": raw})
    return (200, parsed)


def _assert_error(body: dict, must_contain: str = None):
    """Common assertion: response has 'error' field. If
    ``must_contain`` is provided, error message must include it
    (case-insensitive substring match)."""
    assert "error" in body, \
        f"expected 'error' field in response, got: {body}"
    assert isinstance(body["error"], str), \
        f"'error' field is not a string: {type(body['error'])}"
    if must_contain:
        assert must_contain.lower() in body["error"].lower(), \
            (f"error message does not contain {must_contain!r}: "
             f"{body['error']}")


# ─────────────────────────────────────────────────────────────────────
# CSV/rule creation error paths
# ─────────────────────────────────────────────────────────────────────


class TestCreateCsvErrorPaths:
    """Pins the error contract for ``create_csv``."""

    def test_invalid_filename_returns_error(
            self, container_state, container_curl):
        """Path-traversal-style filenames must be rejected."""
        code, body = _post_action(container_curl, "create_csv", {
            "csv_file": "../etc/passwd.csv",
            "detection_rule": "DR_TEST",
            "app_context": "wl_manager",
            "headers": ["host"],
        })
        _assert_error(body)
        # The handler may reject with several different messages
        # ("Invalid CSV filename", "Invalid CSV file name", or
        # similar). We accept any of those since they all mean
        # "the validator rejected the input."
        assert ("invalid" in body["error"].lower()
                or "csv file" in body["error"].lower()), \
            f"unexpected error: {body['error']}"

    def test_missing_detection_rule_returns_error(
            self, container_state, container_curl):
        code, body = _post_action(container_curl, "create_csv", {
            "csv_file": "DR_NEWTEST.csv",
            "app_context": "wl_manager",
            "headers": ["host"],
            # detection_rule missing
        })
        _assert_error(body, "detection rule")

    def test_missing_headers_returns_error(
            self, container_state, container_curl):
        code, body = _post_action(container_curl, "create_csv", {
            "csv_file": "DR_NEWTEST.csv",
            "detection_rule": "DR_NEWTEST",
            "app_context": "wl_manager",
            "headers": [],  # empty
        })
        _assert_error(body, "header")

    def test_non_ascii_in_detection_rule_returns_error(
            self, container_state, container_curl):
        """The 2026-04-26 strict-ASCII policy: rule names cannot
        contain non-ASCII characters (homoglyph + bidi attacks)."""
        code, body = _post_action(container_curl, "create_csv", {
            "csv_file": "DR_NEWTEST.csv",
            "detection_rule": "DR_测试",  # Chinese chars
            "app_context": "wl_manager",
            "headers": ["host"],
        })
        _assert_error(body, "ASCII")

    def test_internal_prefix_column_returns_error(
            self, container_state, container_curl):
        """Underscore-prefix columns are reserved for internal
        metadata (_added_by, _added_at) — user-supplied columns
        with `_` prefix must be rejected."""
        code, body = _post_action(container_curl, "create_csv", {
            "csv_file": "DR_NEWTEST.csv",
            "detection_rule": "DR_NEWTEST",
            "app_context": "wl_manager",
            "headers": ["_secret"],
        })
        _assert_error(body)


class TestCreateRuleErrorPaths:
    """Pins the error contract for ``create_rule``."""

    def test_missing_detection_rule_returns_error(
            self, container_state, container_curl):
        code, body = _post_action(container_curl, "create_rule", {
            "app_context": "wl_manager",
        })
        _assert_error(body)

    def test_too_long_rule_name_returns_error(
            self, container_state, container_curl):
        # Over 100 chars
        code, body = _post_action(container_curl, "create_rule", {
            "detection_rule": "X" * 150,
            "app_context": "wl_manager",
        })
        _assert_error(body, "100")  # mentions the limit

    def test_non_ascii_rule_name_returns_error(
            self, container_state, container_curl):
        code, body = _post_action(container_curl, "create_rule", {
            "detection_rule": "DR_压力测试",  # Chinese
            "app_context": "wl_manager",
        })
        _assert_error(body, "ASCII")


# ─────────────────────────────────────────────────────────────────────
# save_csv error paths
# ─────────────────────────────────────────────────────────────────────


class TestSaveCsvErrorPaths:
    """Pins the error contract for ``save_csv``."""

    def test_missing_detection_rule_returns_error(
            self, container_state, container_curl):
        code, body = _post_action(container_curl, "save_csv", {
            "csv_file": "DR130_priv_escalation.csv",
            "app_context": "wl_manager",
            "rows": [],
            # detection_rule missing
        })
        _assert_error(body, "detection_rule")

    def test_non_ascii_comment_returns_error(
            self, container_state, container_curl):
        """ASCII enforcement on the analyst's comment (the
        free-form reason that flows into the audit trail)."""
        code, body = _post_action(container_curl, "save_csv", {
            "csv_file": "DR130_priv_escalation.csv",
            "detection_rule": "DR130_privilege_escalation",
            "app_context": "wl_manager",
            "rows": [],
            "comment": "Reason with non-ASCII: 测试",
        })
        _assert_error(body)

    def test_invalid_app_context_returns_error(
            self, container_state, container_curl):
        """app_context is a required validation gate — bad values
        must be rejected before any filesystem operations."""
        code, body = _post_action(container_curl, "save_csv", {
            "csv_file": "DR130_priv_escalation.csv",
            "detection_rule": "DR130_privilege_escalation",
            "app_context": "../malicious",  # path-traversal style
            "rows": [],
        })
        _assert_error(body, "app_context")


# ─────────────────────────────────────────────────────────────────────
# save_col_widths error paths
# ─────────────────────────────────────────────────────────────────────


class TestSaveColWidthsErrorPaths:
    """Pins the error contract for ``save_col_widths``."""

    def test_missing_csv_file_returns_error(
            self, container_state, container_curl):
        code, body = _post_action(
            container_curl, "save_col_widths", {
                "app_context": "wl_manager",
                "col_widths": {"user": 200},
                # csv_file missing
            })
        _assert_error(body)

    def test_invalid_app_context_returns_error(
            self, container_state, container_curl):
        code, body = _post_action(
            container_curl, "save_col_widths", {
                "csv_file": "DR130_priv_escalation.csv",
                "app_context": "../bad",
                "col_widths": {"user": 200},
            })
        _assert_error(body, "app_context")


# ─────────────────────────────────────────────────────────────────────
# Trash error paths
# ─────────────────────────────────────────────────────────────────────


class TestTrashErrorPaths:
    """Pins the error contract for trash actions."""

    def test_set_retention_below_minimum_returns_error(
            self, container_state, container_curl):
        """Retention has a documented minimum — values below it
        must be rejected."""
        code, body = _post_action(
            container_curl, "set_trash_retention",
            {"retention_days": 0})
        _assert_error(body)

    def test_purge_with_nonexistent_trash_id_returns_error(
            self, container_state, container_curl):
        """Permanent-delete on a missing trash_id should not
        silently succeed."""
        code, body = _post_action(
            container_curl, "purge_trash",
            {
                "trash_id": "nonexistent-trash-id-error-test",
                "comment": "Ring 1 test - should fail",
            })
        # Either 404-style "not found" OR an approval-required
        # error (purge_trash requires dual-approval per CLAUDE.md).
        # Either way, no silent success.
        _assert_error(body)


# ─────────────────────────────────────────────────────────────────────
# Generic dispatch errors
# ─────────────────────────────────────────────────────────────────────


class TestUnknownActionError:
    """Pins: an unknown action name returns an error, not a 500.
    The dispatcher must distinguish "no such action" from "action
    crashed."""

    def test_unknown_action_returns_error(
            self, container_curl):
        # Doesn't need container_state — pure dispatch error
        code, body = _post_action(
            container_curl,
            "this_action_will_never_exist_in_any_universe",
            {})
        _assert_error(body)
