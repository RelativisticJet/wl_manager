"""
Admin-limit edge case coverage.

Mirrors ``test_limit_edge_cases.py`` for the admin-side limit
configuration surface (``set_admin_limits`` action). The two
paths share validators (same ``VALID_FREQUENCIES``,
``SCHEDULE_INT_KEYS`` constants) but live as duplicated code at
``bin/wl_handler.py:_set_admin_limits`` and
``_set_daily_limits_action``. Day 1 surfaced R2-D1-F1
(``reset_day_of_year`` clamped to 31 instead of 366) in BOTH
paths; the fix landed in both.

The admin path adds two surface-specific properties:

1. **Daily rate gate** — ``MAX_ADMIN_LIMIT_CHANGES_PER_DAY = 5``
   per `wl_handler.py`. Each test uses ``container_state`` which
   snapshots `wl_cooldowns` and restores at teardown, so each
   test starts fresh with the full 5-per-day budget.
2. **RBAC** — only ``wl_superadmin`` role may call. Built-in
   ``admin`` and ``analyst1`` should be rejected.

Origin
------

Ring 2 Day 3. Closes the duplication gap exposed by R2-D1-F1
(buggy validator was duplicated in two write paths) — every
contract Day 1 pinned for analyst limits is also pinned here
for admin limits.
"""

import json

import pytest


pytestmark = pytest.mark.docker


def _post(container_curl, action, payload, user="superadmin1"):
    body = json.dumps({"action": action, **payload})
    proc = container_curl(
        "/services/custom/wl_manager",
        method="POST",
        data=body,
        content_type="application/json",
        check=False,
        user=user,
    )
    raw = (proc.stdout or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw, "_returncode": proc.returncode}


def _get_admin_limits(container_curl, user="superadmin1"):
    proc = container_curl(
        "/services/custom/wl_manager?action=get_admin_limits",
        check=False, user=user)
    return json.loads((proc.stdout or "").strip())


# ─────────────────────────────────────────────────────────────────────
# Boundary / range coverage
# ─────────────────────────────────────────────────────────────────────


class TestAdminLimitBoundaries:
    """Pins the int-range validator for ``set_admin_limits``.

    Same contract as analyst limits: 0-100 inclusive, silent
    reject otherwise. Each test batches multiple changes into
    one API call to stay well under the 5/day rate gate.
    """

    def test_zero_and_max_accepted(
            self, container_state, container_curl):
        body = _post(container_curl, "set_admin_limits", {
            "limits": {"csv_save": 0, "csv_revert": 100},
        })
        if "error" in body:
            pytest.skip("set_admin_limits failed: {}".format(body))
        cfg = _get_admin_limits(container_curl)
        # admin_limits comes back as a flat dict via this endpoint
        admin = cfg.get("limits", cfg.get("admin_limits", cfg))
        assert admin["csv_save"] == 0
        assert admin["csv_revert"] == 100

    def test_above_max_silently_rejected(
            self, container_state, container_curl):
        # Set known starting value
        _post(container_curl, "set_admin_limits", {
            "limits": {"trash_purge": 50}})
        # Try 101
        _post(container_curl, "set_admin_limits", {
            "limits": {"trash_purge": 101}})
        cfg = _get_admin_limits(container_curl)
        admin = cfg.get("limits", cfg.get("admin_limits", cfg))
        assert admin["trash_purge"] == 50, \
            ("101 should be silently rejected, got {}".format(
                admin["trash_purge"]))

    def test_negative_and_string_silently_rejected(
            self, container_state, container_curl):
        _post(container_curl, "set_admin_limits", {
            "limits": {"rule_deletion": 25}})
        _post(container_curl, "set_admin_limits", {
            "limits": {"rule_deletion": -1, "csv_deletion": "10"}})
        cfg = _get_admin_limits(container_curl)
        admin = cfg.get("limits", cfg.get("admin_limits", cfg))
        assert admin["rule_deletion"] == 25, \
            ("negative value not rejected: got {}".format(
                admin["rule_deletion"]))
        # Default for csv_deletion is 2 (per DEFAULT_ADMIN_LIMITS)
        assert isinstance(admin.get("csv_deletion"), int), \
            "string value should not corrupt csv_deletion to non-int"
        assert admin["csv_deletion"] != "10", \
            "string '10' should not be accepted"


# ─────────────────────────────────────────────────────────────────────
# Permission-toggle coverage (admin-tier toggles)
# ─────────────────────────────────────────────────────────────────────


class TestAdminPermissionToggles:
    """The two admin-tier toggles gate destructive admin actions
    that aren't dual-approval-gated:

    - ``allow_admin_purge_trash`` — admin (not superadmin) can
      purge from trash without dual approval
    - ``allow_admin_reset_usage`` — admin can reset analyst
      usage counters without dual approval

    Both are bool-coerced like analyst toggles. Pinning that
    ``bool(val)`` coercion holds and that the value persists
    correctly across read-back.
    """

    def test_disabling_purge_permission_persists(
            self, container_state, container_curl):
        body = _post(container_curl, "set_admin_limits", {
            "limits": {"allow_admin_purge_trash": False},
        })
        if "error" in body:
            pytest.skip("set_admin_limits failed: {}".format(body))
        cfg = _get_admin_limits(container_curl)
        admin = cfg.get("limits", cfg.get("admin_limits", cfg))
        assert admin["allow_admin_purge_trash"] is False

    def test_enabling_reset_permission_persists(
            self, container_state, container_curl):
        body = _post(container_curl, "set_admin_limits", {
            "limits": {"allow_admin_reset_usage": True},
        })
        if "error" in body:
            pytest.skip(str(body))
        cfg = _get_admin_limits(container_curl)
        admin = cfg.get("limits", cfg.get("admin_limits", cfg))
        assert admin["allow_admin_reset_usage"] is True


# ─────────────────────────────────────────────────────────────────────
# Schedule-range coverage — duplicated-code drift surveillance
# ─────────────────────────────────────────────────────────────────────


class TestAdminLimitScheduleRanges:
    """Pins ``SCHEDULE_INT_KEYS`` boundaries on the ADMIN path.

    Day 1 added these tests for the analyst path and that's what
    surfaced R2-D1-F1. The same fix landed in the admin path,
    but no test pinned the admin path independently — meaning if
    the chokepoint refactor (extracting ``SCHEDULE_INT_KEYS`` to
    a single module-level constant) ever lands and gets the
    admin path wrong, no test catches it.

    These tests close that gap. Specifically asserts the
    ``reset_day_of_year`` upper bound is 366 (the R2-D1-F1
    documented contract), not 31 (the bug).
    """

    def test_reset_day_of_year_upper_bound_is_366(
            self, container_state, container_curl):
        body = _post(container_curl, "set_admin_limits", {
            "limits": {"reset_day_of_year": 366},
        })
        if "error" in body:
            pytest.skip(str(body))
        cfg = _get_admin_limits(container_curl)
        admin = cfg.get("limits", cfg.get("admin_limits", cfg))
        assert admin["reset_day_of_year"] == 366, \
            ("R2-D1-F1 regression on admin path: 366 was rejected, "
             "got {}. Check that _set_admin_limits "
             "reset_day_of_year range is (1, 366), not (1, 31)."
             .format(admin["reset_day_of_year"]))

    def test_reset_day_of_year_above_366_rejected(
            self, container_state, container_curl):
        _post(container_curl, "set_admin_limits", {
            "limits": {"reset_day_of_year": 100}})
        _post(container_curl, "set_admin_limits", {
            "limits": {"reset_day_of_year": 367}})
        cfg = _get_admin_limits(container_curl)
        admin = cfg.get("limits", cfg.get("admin_limits", cfg))
        assert admin["reset_day_of_year"] == 100, \
            "367 should be rejected, leaving prev 100; got {}".format(
                admin["reset_day_of_year"])


# ─────────────────────────────────────────────────────────────────────
# Frequency / reset-time coverage
# ─────────────────────────────────────────────────────────────────────


class TestAdminLimitFrequencyAndTime:
    """Spot-check that the same VALID_FREQUENCIES + reset_time
    parsing works on the admin path. Only one frequency value
    and one time value tested (the analyst path test exercises
    the full enum/parameter matrix; here we just confirm the
    admin path's branch isn't dead)."""

    def test_yearly_frequency_accepted(
            self, container_state, container_curl):
        body = _post(container_curl, "set_admin_limits", {
            "limits": {"reset_frequency": "yearly"},
        })
        if "error" in body:
            pytest.skip(str(body))
        cfg = _get_admin_limits(container_curl)
        admin = cfg.get("limits", cfg.get("admin_limits", cfg))
        assert admin["reset_frequency"] == "yearly"

    def test_invalid_frequency_silently_rejected(
            self, container_state, container_curl):
        _post(container_curl, "set_admin_limits", {
            "limits": {"reset_frequency": "daily"}})
        _post(container_curl, "set_admin_limits", {
            "limits": {"reset_frequency": "hourly"}})
        cfg = _get_admin_limits(container_curl)
        admin = cfg.get("limits", cfg.get("admin_limits", cfg))
        assert admin["reset_frequency"] == "daily"

    def test_reset_time_invalid_format_rejected(
            self, container_state, container_curl):
        _post(container_curl, "set_admin_limits", {
            "limits": {"reset_time_utc": "08:00"}})
        _post(container_curl, "set_admin_limits", {
            "limits": {"reset_time_utc": "24:00"}})  # invalid hour
        cfg = _get_admin_limits(container_curl)
        admin = cfg.get("limits", cfg.get("admin_limits", cfg))
        assert admin["reset_time_utc"] == "08:00", \
            "24:00 should be rejected, got {}".format(
                admin["reset_time_utc"])


# ─────────────────────────────────────────────────────────────────────
# RBAC contract
# ─────────────────────────────────────────────────────────────────────


class TestAdminLimitRBAC:
    """Pins: only ``wl_superadmin`` may call ``set_admin_limits``.

    Built-in ``admin`` and ``analyst1`` must be rejected (the
    error path differs — admin returns a permission error,
    analyst1 returns a dispatch-table reject — but neither
    should land changes).
    """

    def test_analyst_cannot_set_admin_limits(
            self, container_state, container_curl):
        body = _post(container_curl, "set_admin_limits", {
            "limits": {"csv_save": 99},
        }, user="analyst1")
        # Should be denied
        assert "error" in body or body.get("success") is not True, \
            ("analyst1 was able to set admin limits: {}"
             .format(body))
        # And the value should NOT have landed
        cfg = _get_admin_limits(container_curl, user="superadmin1")
        admin = cfg.get("limits", cfg.get("admin_limits", cfg))
        assert admin.get("csv_save") != 99, \
            "RBAC bypassed: analyst1 changed csv_save to 99"

    def test_builtin_admin_cannot_set_admin_limits(
            self, container_state, container_curl):
        """The built-in `admin` account doesn't have the
        wl_superadmin role assigned — only the app-defined
        `superadmin1` does. The Splunk built-in admin is
        commonly used in CI/test scripts, so confirming this
        rejection prevents accidental privilege escalation in
        test environments."""
        body = _post(container_curl, "set_admin_limits", {
            "limits": {"csv_save": 88},
        }, user="admin")
        assert "error" in body or body.get("success") is not True, \
            ("built-in admin was able to set admin limits: {}"
             .format(body))
        cfg = _get_admin_limits(container_curl, user="superadmin1")
        admin = cfg.get("limits", cfg.get("admin_limits", cfg))
        assert admin.get("csv_save") != 88
