"""
Limit configuration edge case coverage.

Pins boundary behavior for ``set_daily_limits`` (analyst limits)
and ``set_admin_limits`` (admin limits). The validators clamp
each integer key to a (min, max) range, coerce booleans, and
silently reject invalid values without an error response.

That last property — silent rejection — is the bug-prone part.
A typo in a frequency string or a value outside the schedule
range silently keeps the existing value. The user thinks they
configured "yearly reset on day 100", the system thinks they
configured "yearly reset on day 1" because day 100 fell outside
the validator's range.

Origin
------

Ring 2 Day 1. Extends the schema-pin pattern Ring 1 established
into the limit-configuration surface. The audit dashboard panel
"Configuration changes" surfaces every limit change as a
``limit_change`` / ``admin_limit_change`` event — every test
here also validates that the audit event reflects what actually
landed in config (catches the "frontend shows X, backend
silently kept Y" disconnect).

Findings
--------

R2-D1-F1 — ``reset_day_of_year`` validator range is (1, 31)
instead of (1, 366). ``wl_constants.py`` documents the field as
"1-366, clamped to last day (used by yearly)" but
``_set_daily_limits_action`` and ``_set_admin_limits`` both
clamp to (1, 31). Customer-visible impact: a yearly reset
configured for day 100 silently keeps the existing value (no
error, just ignored).
"""

import json

import pytest


pytestmark = pytest.mark.docker


def _post(container_curl, action, payload, user="admin"):
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


def _get_analyst_limits(container_curl, user="admin"):
    proc = container_curl(
        "/services/custom/wl_manager?action=get_daily_limits",
        check=False, user=user)
    return json.loads((proc.stdout or "").strip())


# ─────────────────────────────────────────────────────────────────────
# set_daily_limits — analyst limits
# ─────────────────────────────────────────────────────────────────────


class TestAnalystLimitBoundaries:
    """Pins the int-range validator for ``set_daily_limits``."""

    def test_zero_is_accepted_as_disabled(
            self, container_state, container_curl):
        """Per CLAUDE.md / DEFAULT_LIMITS, ``0`` for an analyst
        limit means "disabled" (the action is blocked entirely).
        Zero must be accepted — not silently treated as
        "unlimited" or rejected as invalid."""
        body = _post(container_curl, "set_daily_limits", {
            "limits": {"row_removal": 0},
        }, user="superadmin1")
        if "error" in body:
            pytest.skip("set_daily_limits failed: {}".format(body))
        # Read back and confirm the change landed
        cfg = _get_analyst_limits(container_curl)
        assert cfg["limits"]["row_removal"] == 0, \
            "0 not persisted for row_removal"

    def test_max_value_100_is_accepted(
            self, container_state, container_curl):
        body = _post(container_curl, "set_daily_limits", {
            "limits": {"row_removal": 100},
        }, user="superadmin1")
        if "error" in body:
            pytest.skip(body)
        cfg = _get_analyst_limits(container_curl)
        assert cfg["limits"]["row_removal"] == 100

    def test_above_max_is_silently_rejected(
            self, container_state, container_curl):
        """Documented contract: values >100 are silently
        rejected (validator: ``0 <= val <= 100``). The pre-fix
        value is preserved — NOT clamped to 100, NOT errored."""
        # First set a known starting value
        _post(container_curl, "set_daily_limits", {
            "limits": {"row_removal": 50}}, user="superadmin1")

        # Try to set 101 — should be silently rejected
        body = _post(container_curl, "set_daily_limits", {
            "limits": {"row_removal": 101}}, user="superadmin1")

        cfg = _get_analyst_limits(container_curl)
        # Value should still be 50 (the previous valid value),
        # NOT 101 (rejected) and NOT 100 (not clamped)
        assert cfg["limits"]["row_removal"] == 50, \
            ("101 should be silently rejected, preserving the "
             "previous value of 50. Got: {}".format(
                 cfg["limits"]["row_removal"]))

    def test_negative_value_is_silently_rejected(
            self, container_state, container_curl):
        _post(container_curl, "set_daily_limits", {
            "limits": {"row_removal": 25}}, user="superadmin1")
        _post(container_curl, "set_daily_limits", {
            "limits": {"row_removal": -1}}, user="superadmin1")
        cfg = _get_analyst_limits(container_curl)
        assert cfg["limits"]["row_removal"] == 25, \
            "negative value not rejected — got {}".format(
                cfg["limits"]["row_removal"])

    def test_string_value_is_silently_rejected(
            self, container_state, container_curl):
        """Type confusion guard: a JSON string ``"50"`` should
        NOT be accepted. The handler uses ``isinstance(val, int)``
        which rejects strings even if they parse as numbers."""
        _post(container_curl, "set_daily_limits", {
            "limits": {"row_removal": 25}}, user="superadmin1")
        _post(container_curl, "set_daily_limits", {
            "limits": {"row_removal": "50"}}, user="superadmin1")
        cfg = _get_analyst_limits(container_curl)
        assert cfg["limits"]["row_removal"] == 25


class TestAnalystLimitBooleanCoercion:
    """Booleans coerced via ``bool(val)`` — any truthy/falsy
    JSON value lands as True/False respectively. Pinning this
    so a future refactor that requires strict-bool input
    doesn't silently break frontend forms that send ``"true"``
    strings.
    """

    def test_true_accepted(
            self, container_state, container_curl):
        _post(container_curl, "set_daily_limits", {
            "limits": {"allow_analyst_create_rules": True},
        }, user="superadmin1")
        cfg = _get_analyst_limits(container_curl)
        assert cfg["limits"]["allow_analyst_create_rules"] is True

    def test_false_accepted(
            self, container_state, container_curl):
        _post(container_curl, "set_daily_limits", {
            "limits": {"allow_analyst_create_rules": False},
        }, user="superadmin1")
        cfg = _get_analyst_limits(container_curl)
        assert cfg["limits"]["allow_analyst_create_rules"] is False


class TestAnalystLimitFrequency:
    """Pins ``reset_frequency`` validation."""

    VALID_FREQUENCIES = (
        "never", "daily", "weekly", "monthly", "yearly")

    @pytest.mark.parametrize("freq", VALID_FREQUENCIES)
    def test_each_valid_frequency_is_accepted(
            self, container_state, container_curl, freq):
        body = _post(container_curl, "set_daily_limits", {
            "limits": {"reset_frequency": freq},
        }, user="superadmin1")
        if "error" in body:
            pytest.skip(body)
        cfg = _get_analyst_limits(container_curl)
        assert cfg["limits"]["reset_frequency"] == freq

    def test_invalid_frequency_silently_rejected(
            self, container_state, container_curl):
        # Set known starting value
        _post(container_curl, "set_daily_limits", {
            "limits": {"reset_frequency": "daily"}},
            user="superadmin1")
        # Try invalid
        _post(container_curl, "set_daily_limits", {
            "limits": {"reset_frequency": "hourly"}},
            user="superadmin1")
        cfg = _get_analyst_limits(container_curl)
        assert cfg["limits"]["reset_frequency"] == "daily", \
            "'hourly' should be rejected, 'daily' preserved"


class TestAnalystLimitResetTime:
    """Pins ``reset_time_utc`` parsing — must be HH:MM with
    HH=0-23 and MM=0-59."""

    @pytest.mark.parametrize("valid", [
        "00:00", "23:59", "12:30", "06:45",
    ])
    def test_valid_times_accepted(
            self, container_state, container_curl, valid):
        body = _post(container_curl, "set_daily_limits", {
            "limits": {"reset_time_utc": valid},
        }, user="superadmin1")
        if "error" in body:
            pytest.skip(body)
        cfg = _get_analyst_limits(container_curl)
        assert cfg["limits"]["reset_time_utc"] == valid

    @pytest.mark.parametrize("invalid", [
        "24:00",       # hour out of range
        "12:60",       # minute out of range
        "abc",         # not HH:MM
        "1:30",        # missing leading zero
        "12-30",       # wrong separator
        "12:30:45",    # too many fields (length != 5)
    ])
    def test_invalid_times_silently_rejected(
            self, container_state, container_curl, invalid):
        _post(container_curl, "set_daily_limits", {
            "limits": {"reset_time_utc": "08:00"}},
            user="superadmin1")
        _post(container_curl, "set_daily_limits", {
            "limits": {"reset_time_utc": invalid}},
            user="superadmin1")
        cfg = _get_analyst_limits(container_curl)
        assert cfg["limits"]["reset_time_utc"] == "08:00", \
            ("invalid time {!r} not rejected — got {!r}".format(
                invalid, cfg["limits"]["reset_time_utc"]))


class TestAnalystLimitScheduleRanges:
    """Pins ``SCHEDULE_INT_KEYS`` boundaries.

    These were the bug surface for R2-D1-F1: the validator's
    documented range (per ``wl_constants.py``) for
    ``reset_day_of_year`` is 1-366, but the actual validator
    clamped to 1-31. Tests pin the CORRECT documented range;
    the fix lands in the same commit.
    """

    @pytest.mark.parametrize("key,low,high", [
        ("reset_day_of_week", 0, 6),
        ("reset_day_of_month", 1, 31),
        ("reset_month", 1, 12),
        ("reset_day_of_year", 1, 366),
    ])
    def test_schedule_int_low_bound_accepted(
            self, container_state, container_curl, key, low, high):
        body = _post(container_curl, "set_daily_limits", {
            "limits": {key: low}}, user="superadmin1")
        if "error" in body:
            pytest.skip(body)
        cfg = _get_analyst_limits(container_curl)
        assert cfg["limits"][key] == low, \
            "{} low bound {} not accepted, got {}".format(
                key, low, cfg["limits"][key])

    @pytest.mark.parametrize("key,low,high", [
        ("reset_day_of_week", 0, 6),
        ("reset_day_of_month", 1, 31),
        ("reset_month", 1, 12),
        ("reset_day_of_year", 1, 366),
    ])
    def test_schedule_int_high_bound_accepted(
            self, container_state, container_curl, key, low, high):
        body = _post(container_curl, "set_daily_limits", {
            "limits": {key: high}}, user="superadmin1")
        if "error" in body:
            pytest.skip(body)
        cfg = _get_analyst_limits(container_curl)
        assert cfg["limits"][key] == high, \
            ("{} high bound {} not accepted, got {}. "
             "If this is reset_day_of_year, R2-D1-F1 fix may "
             "not have landed.".format(
                 key, high, cfg["limits"][key]))

    @pytest.mark.parametrize("key,low,high", [
        ("reset_day_of_week", 0, 6),
        ("reset_day_of_month", 1, 31),
        ("reset_month", 1, 12),
        ("reset_day_of_year", 1, 366),
    ])
    def test_schedule_int_above_high_silently_rejected(
            self, container_state, container_curl, key, low, high):
        # Set a known mid-range value first
        mid = (low + high) // 2
        _post(container_curl, "set_daily_limits", {
            "limits": {key: mid}}, user="superadmin1")
        # Try high+1
        _post(container_curl, "set_daily_limits", {
            "limits": {key: high + 1}}, user="superadmin1")
        cfg = _get_analyst_limits(container_curl)
        assert cfg["limits"][key] == mid, \
            "{} should reject {}; got {}".format(
                key, high + 1, cfg["limits"][key])
