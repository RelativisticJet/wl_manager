# Ring 1 Input — Handler Contract Tests Inventory

Generated 2026-05-07 as part of Ring 0 cleanup (option C — delete
zombies, rewrite high-value contracts as proper Ring 1 work).

This file captures the test ideas from the 94 deleted zombie tests
(see `RING_FINDINGS.md` R0-F2) so the same scenarios can be
rewritten properly in Ring 1 with mutation gates.

The 94 tests are grouped by value tier. Ring 1 should rewrite the
HIGH-value ones; the LOW-value ones can be dropped.

## HIGH value (rewrite in Ring 1) — ~70 tests

### Dispatch table integrity (~10 tests)

Catches silent wiring bugs — action wired to wrong method, role
tier missing, duplicate action names.

- `test_get_actions_table_exists` — GET_ACTIONS dict exists on handler
- `test_get_actions_table_structure` — every entry is `(roles, method_name)` tuple
- `test_post_actions_table_exists` — POST_ACTIONS dict exists
- `test_post_actions_table_structure` — same shape check for POST
- `test_get_actions_have_handler_methods` — every method_name in GET_ACTIONS resolves
- `test_post_actions_have_handler_methods` — same for POST
- `test_no_duplicate_action_names` — no action name appears twice
- `test_no_public_actions_without_roles` — every dispatch entry has a roles tuple (no None except where intentionally public, e.g. notifications)
- `test_admin_only_actions_marked` — known-admin actions have ADMIN_ROLES
- `test_all_action_methods_follow_naming` — `_action_<name>` convention

### POST happy-path contracts (~20 tests)

Catches projection drift — the build-641 bug class. Each test must
inspect the FULL response shape, not just top-level keys.

- `test_create_csv_success` — response carries success flag, csv_file echo
- `test_create_rule_success` — response carries rule_name, mapping update visible
- `test_save_csv_success` — response carries diff, version_id, content_hash, file_mtime, all expected fields
- `test_save_col_widths_success` — response shape
- `test_purge_trash_success` — response shape + audit emission
- `test_restore_from_trash_success` — response shape + audit emission
- `test_set_trash_retention_success` — response shape + config persists
- `test_save_as_default_success` — response shape
- `test_reset_factory_defaults_success` — response shape + config reverts
- `test_submit_approval_success` — response carries request_id, queue grew by 1
- `test_process_approval_approve_success` — response shape, queue entry resolved, replay fired
- `test_process_approval_reject_success` — response shape, queue entry resolved, NO replay
- `test_cancel_request_success` — response shape, queue entry removed
- `test_mark_notifications_read_with_ids` — response, target IDs marked
- `test_mark_all_notifications_read` — bulk variant
- `test_log_csv_exported_event` — emits audit event with all expected fields
- `test_log_csv_imported_event` — same
- `test_log_audit_exported_event` — same
- `test_save_csv_small_edit_no_approval` — gate not triggered for small edit
- `test_save_csv_bulk_edit_requires_approval` — gate triggered for bulk edit

### POST error-path contracts (~15 tests)

Error responses are part of the contract. Often where projection
drift hides because errors aren't checked as carefully as happy paths.

- `test_create_csv_invalid_filename` — 400 with `error` field
- `test_create_csv_missing_file` — 400 with `error` field
- `test_create_csv_already_exists` — 409 conflict
- `test_create_rule_invalid_name` — 400
- `test_create_rule_missing_name` — 400
- `test_create_rule_already_exists` — 409
- `test_save_col_widths_csv_not_found` — 404
- `test_save_col_widths_missing_csv_file` — 400
- `test_save_col_widths_invalid_col_widths` — 400
- `test_purge_trash_item_not_found` — 404
- `test_restore_from_trash_error` — error path
- `test_set_trash_retention_invalid_days` — 400
- `test_cancel_request_missing_reason` — 400
- `test_cancel_request_not_found` — 404
- `test_cancel_request_not_requester` — 403
- `test_submit_approval_missing_action` — 400
- `test_submit_approval_invalid_action_type` — 400
- `test_log_event_invalid_action` — 400
- `test_invalid_action_name` — generic unknown-action 400
- `test_handle_get_missing_action_returns_400` — GET no action param
- `test_handle_post_unknown_user_returns_401` — auth missing
- `test_error_response_has_error_field` — every error response has `error` key
- `test_success_response_has_success_field` — happy path consistency

### Approval workflow contracts (~10 tests)

The approval gate is the highest-value security boundary. Must have
deep tests.

- `test_save_csv_bulk_edit_requires_approval` — gate triggers
- `test_remove_csv_bulk_triggers_approval` — bulk-remove gate
- `test_remove_csv_conflict_cancels_pending` — auto-cancel logic
- `test_process_approval_approve_success` — full approve flow
- `test_process_approval_reject_success` — full reject flow
- `test_process_approval_request_not_found` — 404 on missing request
- `test_process_approval_reject_no_change_to_csv` — reject doesn't replay
- `test_process_approval_audit_includes_approval_metadata` — audit fields after approve
- `test_analyst_cannot_approve_own_request` — RBAC self-approval block
- `test_superadmin_can_approve_any_request` — RBAC bypass for superadmin

### Audit-emission contracts (~3 tests)

Verifies that audit-emitting actions actually emit. Pairs with
CLAUDE.md "Audit Trail Verification" rule.

- `test_log_csv_exported_event` — audit event fields present
- `test_log_csv_imported_event` — same
- `test_log_audit_exported_event` — same

## LOW value (drop) — ~24 tests

### "Method exists" trivialities

These check `hasattr(handler, '_action_X')`. Python would raise
`AttributeError` at first dispatch attempt if the method were
missing — these tests provide no signal beyond what runtime gives
us for free.

- `test_action_create_rule_exists`
- `test_action_get_csv_content_exists`
- `test_action_get_csvs_exists`
- `test_action_get_mapping_exists`
- `test_action_get_rules_exists`
- `test_action_process_approval_exists`
- `test_action_save_csv_exists`
- `test_action_submit_approval_exists`
- `test_each_get_action_is_callable`
- `test_dispatch_method_exists`
- `test_dispatch_method_signature` — meta-test about signature, not behaviour
- `test_handle_get_method_exists`
- `test_handle_post_method_exists`
- `test_get_admin_limits_method_exists`
- `test_get_admin_limits_requires_admin_role` — RBAC tier (covered by `test_rbac.py`)
- `test_get_analyst_usage_method_exists`
- `test_get_analyst_usage_requires_admin_role` — RBAC (covered)
- `test_get_approval_queue_method_exists`
- `test_get_approval_queue_returns_dict` — shallow shape
- `test_get_daily_limits_method_exists`
- `test_get_daily_limits_requires_admin_role` — RBAC (covered)
- `test_get_versions_method_exists`
- `test_get_versions_returns_dict` — shallow shape
- `test_list_trash_method_exists`
- `test_list_trash_returns_dict` — shallow shape
- `test_all_required_get_actions_present` — overlap with dispatch integrity
- `test_all_simple_post_actions_have_methods` — overlap
- `test_all_complex_post_actions_have_methods` — overlap
- `test_approval_workflow_actions_require_admin_role` — RBAC (covered)
- `test_missing_required_roles` — RBAC (covered)
- `test_save_col_widths_signature` — meta-test
- `test_log_event_signature` — meta-test
- `test_cancel_request_signature` — meta-test
- `test_mark_notifications_read_signature` — meta-test

## Ring 1 implementation note

Each HIGH-value test in Ring 1 must:

1. Run against the real `wl_manager_test` container (per user
   "container tests for accuracy" decision)
2. Inspect the FULL response shape — every field, not just top-level
3. Have a corresponding mutation gate at ring close (sabotage the
   handler in 1-2 ways the test should catch, confirm failure)
4. Use the conftest container-snapshot fixture (to be built in Ring 1
   day 1) so test order doesn't matter and state doesn't accumulate
