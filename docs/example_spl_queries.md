# Example SPL Queries for Whitelist Manager Audit

All queries search the `wl_audit` index. Adjust the time range as needed.

Note: SPL `eval` is a Splunk built-in function for field computation, not JavaScript eval().

## Basic Audit Queries

### All changes in the last 24 hours

```spl
index=wl_audit sourcetype=wl_audit earliest=-24h
| table timestamp analyst action detection_rule csv_file comment
| sort - timestamp
```

### Changes by a specific analyst

```spl
index=wl_audit analyst="jsmith"
| table timestamp action detection_rule csv_file comment
| sort - timestamp
```

### All removals with reasons

```spl
index=wl_audit action IN ("removed", "removed_multiple")
| table timestamp analyst detection_rule csv_file removed_row_count remove_reason value
| sort - timestamp
```

### All edits with before/after values

```spl
index=wl_audit action="edited"
| table timestamp analyst detection_rule csv_file edited_row_count comment value
| sort - timestamp
```

## Approval Workflow Queries

### Pending approval requests

```spl
index=wl_audit action="request_submitted"
| rename request_id AS req_id
| join type=left req_id [
    search index=wl_audit action IN ("request_approved", "request_rejected", "request_cancelled")
    | rename action AS resolution, request_id AS req_id
    | table req_id resolution
]
| where isnull(resolution)
| table timestamp analyst detection_rule csv_file approval_action_type approval_reason req_id
```

### Approval history with admin responses

```spl
index=wl_audit action IN ("request_approved", "request_rejected", "request_cancelled")
| table timestamp analyst action requester detection_rule csv_file approval_action_type rejection_reason cancellation_reason
| sort - timestamp
```

## Revert Queries

### All reverts with version details

```spl
index=wl_audit action="revert"
| table timestamp analyst detection_rule csv_file reverted_from_version reverted_to_version new_record_version restoredback_row_count removedback_row_count editedback_row_count comment
| sort - timestamp
```

## Compliance and Reporting

### Daily change summary by analyst

```spl
index=wl_audit action IN ("added", "removed", "removed_multiple", "edited", "revert")
| bin timestamp span=1d AS date
| stats count AS total_changes, dc(csv_file) AS csvs_modified BY date analyst
| sort - date analyst
```

### Most frequently modified CSVs

```spl
index=wl_audit action IN ("added", "removed", "removed_multiple", "edited")
| stats count AS change_count, dc(analyst) AS unique_analysts, latest(timestamp) AS last_modified BY csv_file detection_rule
| sort - change_count
```

### Auto-expiration events

```spl
index=wl_audit action="auto_removed"
| table timestamp csv_file detection_rule auto_removed_row_count value
| sort - timestamp
```

### Export/import activity

```spl
index=wl_audit action IN ("csv_exported", "csv_imported", "audit_exported")
| table timestamp analyst action detection_rule csv_file row_count comment
| sort - timestamp
```

## Security Monitoring

### High-volume analysts (potential misuse)

```spl
index=wl_audit action IN ("added", "removed", "removed_multiple", "edited") earliest=-7d
| stats count AS total_ops BY analyst
| where total_ops > 50
| sort - total_ops
```
