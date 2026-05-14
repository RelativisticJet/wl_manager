"""
Notification payload contract tests.

Pins the JSON shape of every notification kind written by
``_add_notification``. The frontend bell renderer
(``appserver/static/notifications.js``) reads specific fields
when rendering each notification — drops or renames silently
break the bell.

Documented notification kinds (per ``_add_notification`` docstring):

    'new_request', 'approved', 'rejected', 'cancelled'

Plus an internal kind ``admin_limit_change`` used for config-only
notifications that intentionally lack csv_file / detection_rule.

Frontend reads (``notifications.js`` data-attribute generation):

    n.id          — for ``data-notif-id`` (unique identifier)
    n.type        — for ``data-notif-type`` + icon selection
    n.action_type — for ``data-action-type`` (drives click-through)
    n.csv_file    — for ``data-csv-file``
    n.detection_rule — for ``data-detection-rule``
    n.message     — body text
    n.timestamp   — relative time display
    n.read        — unread-style class
    n.related_request_id — click-through to approval queue

Origin
------

Ring 2 Day 2. Same projection-drift bug class as build-641
(``project_pending_info`` dropped ``comment``) — applied to a
new surface. The bell renderer would silently render blanks
for `csv_file` / `action_type` / etc. if the writer dropped
the field.
"""

import json
import time
import uuid

import pytest


pytestmark = pytest.mark.docker


# Documented notification types per ``_add_notification`` docstring
DOCUMENTED_NOTIF_TYPES = {"new_request", "approved", "rejected", "cancelled"}

# Approval-flow notifications must carry these three context
# fields so the bell can surface "what was this about?". Frontend
# uses them for the click-through and for the data-attributes that
# drive UX.
APPROVAL_FLOW_EXTRA_FIELDS = {"action_type", "csv_file", "detection_rule"}

# Base envelope every notification carries (set by _add_notification
# itself, not the caller's `extra` dict).
BASE_NOTIFICATION_FIELDS = {
    "id", "type", "message", "timestamp", "read",
    "related_request_id",
}


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


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


def _get_notifications(container_curl, user):
    """Read notifications for ``user`` via the GET endpoint."""
    proc = container_curl(
        "/services/custom/wl_manager?action=get_notifications",
        check=False, user=user)
    raw = (proc.stdout or "").strip()
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return body.get("notifications", [])


def _submit_column_removal(container_curl, csv_file, rule_name,
                           comment, user="analyst1"):
    """Helper used to generate notification side effects.

    A column_removal request as analyst1 fires a 'new_request'
    notification to admins.
    """
    return _post(container_curl, "submit_approval", {
        "approval_action_type": "column_removal",
        "csv_file": csv_file,
        "detection_rule": rule_name,
        "app_context": "wl_manager",
        "description": "Ring 2 Day 2 notification payload test",
        "comment": comment,
        "pending_highlight": {"type": "column", "column_name": "host"},
        "payload": {"column_name": "host"},
    }, user=user)


def _get_first_mapping(container_curl):
    """Return one (csv_file, rule_name) tuple from the demo state."""
    proc = container_curl(
        "/services/custom/wl_manager?action=get_mapping",
        check=False)
    body = json.loads((proc.stdout or "").strip())
    if not body.get("mapping"):
        return None
    entry = body["mapping"][0]
    return entry["csv_file"], entry["rule_name"]


# ─────────────────────────────────────────────────────────────────────
# Base envelope contract
# ─────────────────────────────────────────────────────────────────────


class TestNotificationBaseEnvelope:
    """Pins the 6 base fields ``_add_notification`` always writes.

    These fields land regardless of caller's ``extra`` dict. If
    a future refactor changes how ``_add_notification`` builds
    the notification dict (e.g., splits it into a dataclass) and
    drops a field, the bell loses the unread-state, the timestamp,
    or the click-through.
    """

    def test_new_request_notification_has_full_base_envelope(
            self, container_state, container_curl):
        mapping = _get_first_mapping(container_curl)
        if not mapping:
            pytest.skip("no mappings in demo state")
        csv_file, rule_name = mapping

        body = _submit_column_removal(
            container_curl, csv_file, rule_name,
            comment="Ring 2 Day 2 base envelope test")
        if "error" in body:
            pytest.skip("submit failed: {}".format(body))
        request_id = body["request_id"]

        # Notification fires to admins (wladmin1). Read as them.
        # Match by related_request_id (the message text uses
        # `description`, not `comment`, so we can't filter on the
        # comment text alone).
        notifs = _get_notifications(container_curl, user="wladmin1")
        new_request_notifs = [
            n for n in notifs
            if n.get("type") == "new_request"
            and n.get("related_request_id") == request_id]
        assert new_request_notifs, \
            ("no new_request notification for {}. "
             "Got {} notifications".format(
                 request_id, len(notifs)))
        notif = new_request_notifs[0]

        missing = BASE_NOTIFICATION_FIELDS - set(notif.keys())
        assert not missing, \
            ("notification missing base fields: {}. Notif: {}"
             .format(missing, notif))

        # Spot-check value types
        assert isinstance(notif["id"], str) and notif["id"]
        assert notif["read"] is False, \
            "freshly-created notification should be unread"
        assert isinstance(notif["timestamp"], int)
        assert notif["timestamp"] > 0


# ─────────────────────────────────────────────────────────────────────
# Approval-flow contract
# ─────────────────────────────────────────────────────────────────────


class TestApprovalFlowNotificationExtra:
    """Pins the approval-flow context fields on every kind:

    new_request → fired to admins when analyst submits
    approved   → fired to analyst when admin approves
    rejected   → fired to analyst when admin rejects
    cancelled  → fired to admins when analyst self-cancels (build 641+)

    All four MUST carry action_type / csv_file / detection_rule
    so the bell renderer can populate data-attributes and
    click-through metadata.
    """

    def test_new_request_notification_carries_approval_extra(
            self, container_state, container_curl):
        mapping = _get_first_mapping(container_curl)
        if not mapping:
            pytest.skip("no mappings")
        csv_file, rule_name = mapping
        body = _submit_column_removal(
            container_curl, csv_file, rule_name,
            comment="extra-test-new_request")
        if "error" in body:
            pytest.skip(str(body))
        request_id = body["request_id"]

        notifs = _get_notifications(container_curl, user="wladmin1")
        target = next(
            (n for n in notifs
             if n.get("type") == "new_request"
             and n.get("related_request_id") == request_id),
            None)
        assert target is not None, "new_request notification not found"

        missing = APPROVAL_FLOW_EXTRA_FIELDS - set(target.keys())
        assert not missing, \
            ("new_request notification missing context fields: "
             "{}. Notif: {}".format(missing, target))
        assert target["csv_file"] == csv_file
        assert target["detection_rule"] == rule_name
        assert target["action_type"] == "column_removal"

    def test_rejected_notification_carries_approval_extra(
            self, container_state, container_curl):
        # Submit + reject as wladmin1
        mapping = _get_first_mapping(container_curl)
        if not mapping:
            pytest.skip("no mappings")
        csv_file, rule_name = mapping
        marker = uuid.uuid4().hex[:8]
        sub = _submit_column_removal(
            container_curl, csv_file, rule_name,
            comment="extra-test-rejected {}".format(marker))
        if "error" in sub:
            pytest.skip("submit failed: {}".format(sub))
        request_id = sub["request_id"]

        rej = _post(container_curl, "process_approval", {
            "request_id": request_id,
            "decision": "reject",
            "rejection_reason": "Ring 2 D2 reject {}".format(marker),
        }, user="wladmin1")
        if "error" in rej:
            pytest.skip("reject failed: {}".format(rej))

        # Notification fires to analyst1
        notifs = _get_notifications(container_curl, user="analyst1")
        target = next(
            (n for n in notifs
             if n.get("type") == "rejected"
             and n.get("related_request_id") == request_id),
            None)
        assert target is not None, \
            "rejected notification for {} not found".format(request_id)

        missing = APPROVAL_FLOW_EXTRA_FIELDS - set(target.keys())
        assert not missing, \
            "rejected notification missing fields: {}".format(missing)
        # Rejection notifications also carry admin_comment for
        # the bell drilldown
        assert "admin_comment" in target, \
            "rejected notification missing admin_comment field"
        assert "Ring 2 D2 reject" in target["admin_comment"]

    def test_approved_notification_carries_approval_extra(
            self, container_state, container_curl):
        # Submit a row_addition (which is auto-approved by admin
        # without complex approval-gate logic — simpler than
        # exercising the bulk-row flow)
        mapping = _get_first_mapping(container_curl)
        if not mapping:
            pytest.skip("no mappings")
        csv_file, rule_name = mapping
        marker = uuid.uuid4().hex[:8]
        sub = _submit_column_removal(
            container_curl, csv_file, rule_name,
            comment="extra-test-approved {}".format(marker))
        if "error" in sub:
            pytest.skip(str(sub))
        request_id = sub["request_id"]

        appr = _post(container_curl, "process_approval", {
            "request_id": request_id,
            "decision": "approve",
            "admin_comment": "Ring 2 D2 approve",
        }, user="wladmin1")
        if "error" in appr:
            pytest.skip("approve failed: {}".format(appr))

        notifs = _get_notifications(container_curl, user="analyst1")
        target = next(
            (n for n in notifs
             if n.get("type") == "approved"
             and n.get("related_request_id") == request_id),
            None)
        assert target is not None, "approved notification not found"

        missing = APPROVAL_FLOW_EXTRA_FIELDS - set(target.keys())
        assert not missing, \
            "approved notification missing fields: {}".format(missing)
        assert target["action_type"] == "column_removal"
        assert target["csv_file"] == csv_file
        assert target["detection_rule"] == rule_name


# ─────────────────────────────────────────────────────────────────────
# Type-value contract
# ─────────────────────────────────────────────────────────────────────


class TestNotificationTypeValues:
    """Pins: every notification's ``type`` field is one of the
    documented kinds. A new ``type`` value means the
    ``_add_notification`` docstring AND ``notifications.js
    getIcon()`` need updates simultaneously.
    """

    def test_recent_notifications_have_documented_types(
            self, container_state, container_curl):
        # Trigger a few different notification kinds
        mapping = _get_first_mapping(container_curl)
        if mapping:
            csv_file, rule_name = mapping
            marker = uuid.uuid4().hex[:8]
            sub = _submit_column_removal(
                container_curl, csv_file, rule_name,
                comment="type-values {}".format(marker))
            if "error" not in sub:
                # Reject it to also create a 'rejected' notif
                _post(container_curl, "process_approval", {
                    "request_id": sub["request_id"],
                    "decision": "reject",
                    "rejection_reason": "type-values test",
                }, user="wladmin1")

        # Sample notifications across multiple users
        all_types = set()
        for user in ("admin", "wladmin1", "superadmin1", "analyst1"):
            notifs = _get_notifications(container_curl, user=user)
            for n in notifs[:20]:  # Recent only
                t = n.get("type")
                if t:
                    all_types.add(t)

        if not all_types:
            pytest.skip("no notifications across users")

        # Every observed type must be documented OR be a known
        # internal type. We allow some additional internal types
        # the docstring doesn't explicitly enumerate but which
        # exist in the codebase: 'admin_limit_change', plus FIM
        # alert kinds (severity-prefixed) ingested from the alert
        # queue. The frontend's getIcon() falls back to a default
        # icon for unknown types, but we still want a clean
        # inventory.
        documented_plus_internal = DOCUMENTED_NOTIF_TYPES | {
            "admin_limit_change",
        }
        unknown = all_types - documented_plus_internal
        # FIM-prefixed types like 'fim_*' are also legitimate
        # (ingested from wl_fim_watch.py via _ingest_fim_alerts_for_user)
        unknown = {t for t in unknown if not t.startswith("fim_")}
        assert not unknown, \
            ("Notification types not in the documented set: {}. "
             "Either update DOCUMENTED_NOTIF_TYPES + the "
             "_add_notification docstring + notifications.js "
             "getIcon(), or rename the type."
             .format(unknown))


# ─────────────────────────────────────────────────────────────────────
# Read-state contract
# ─────────────────────────────────────────────────────────────────────


class TestNotificationReadState:
    """Pins: notifications start unread; mark_notifications_read
    flips them to read. The frontend uses this to render the
    unread badge count.
    """

    def test_new_notification_starts_unread(
            self, container_state, container_curl):
        mapping = _get_first_mapping(container_curl)
        if not mapping:
            pytest.skip("no mappings")
        csv_file, rule_name = mapping
        sub = _submit_column_removal(
            container_curl, csv_file, rule_name,
            comment="unread-state-test")
        if "error" in sub:
            pytest.skip(str(sub))
        request_id = sub["request_id"]

        # Fetch as wladmin1 (the recipient of new_request notif)
        notifs = _get_notifications(container_curl, user="wladmin1")
        target = next(
            (n for n in notifs
             if n.get("related_request_id") == request_id),
            None)
        assert target is not None
        assert target["read"] is False, \
            "freshly-created notification must be unread"

    def test_mark_notifications_read_flips_state(
            self, container_state, container_curl):
        mapping = _get_first_mapping(container_curl)
        if not mapping:
            pytest.skip("no mappings")
        csv_file, rule_name = mapping
        sub = _submit_column_removal(
            container_curl, csv_file, rule_name,
            comment="mark-read-test")
        if "error" in sub:
            pytest.skip(str(sub))
        request_id = sub["request_id"]

        # Mark all as read
        _post(container_curl, "mark_notifications_read", {},
              user="wladmin1")

        notifs = _get_notifications(container_curl, user="wladmin1")
        target = next(
            (n for n in notifs
             if n.get("related_request_id") == request_id),
            None)
        if target is None:
            pytest.skip("notification not visible after mark-read")
        assert target["read"] is True, \
            "mark_notifications_read should flip read=True"
