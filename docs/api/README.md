# Whitelist Manager REST API Documentation

This directory contains the OpenAPI 3.0 specification for the Whitelist Manager REST API and usage guides.

## Overview

The Whitelist Manager API allows developers and integrations to:

- **View CSV whitelists**: Fetch CSV content, mapping, and version history
- **Edit whitelists**: Save changes, add/remove rows, revert to previous versions
- **Manage rules**: Create and delete detection rules
- **Approval workflows**: Submit bulk edits for approval and process them
- **Administration**: Configure daily limits, manage trash, and reset settings
- **Presence tracking**: Track which analysts are currently working on a CSV

The API is fully documented in an OpenAPI 3.0 specification that can be used by automated tools, code generators, and testing frameworks.

## Quick Start

### Base URL

```
https://<your-splunk-instance>:8089/custom/wl_manager
```

### Authentication

All requests require a valid Splunk session key. You have two options:

**Option 1: X-Splunk-Key Header (Recommended)**

```bash
curl -X GET "https://your-splunk:8089/custom/wl_manager?action=get_csv_content&csv_file=DR_Test.csv" \
  -H "X-Splunk-Key: $(curl -k -u admin:password https://your-splunk:8089/services/auth/login -d 'username=admin&password=password' -X POST | grep -oP '<sessionKey>\K[^<]+')" \
  -k
```

**Option 2: session_key Parameter**

```bash
curl -X GET "https://your-splunk:8089/custom/wl_manager?action=get_csv_content&csv_file=DR_Test.csv&session_key=YOUR_SESSION_KEY" \
  -k
```

### Common Parameters

**GET requests:**
- `action` (required): The GET action name
- `csv_file`: CSV filename (required for most actions)
- `app`: App context (for multi-app support)
- `tz_offset`: Timezone offset in minutes (for get_csv_content)

**POST requests:**
- `action` (required): The POST action name (in JSON body)
- Action-specific fields (e.g., `csv_file`, `new_rows`, `old_rows`, `comment`)

### Response Format

All responses are JSON with a `success` field indicating outcome:

**Success Response:**
```json
{
  "success": true,
  "csv_file": "DR_Test.csv",
  "row_count": 42,
  "...": "other fields depending on action"
}
```

**Error Response:**
```json
{
  "success": false,
  "error": "CSV file not found"
}
```

## Common Use Cases

### 1. Get CSV Content

Fetch the content of a CSV lookup file:

```bash
curl -X GET \
  "https://your-splunk:8089/custom/wl_manager?action=get_csv_content&csv_file=DR_BruteForce.csv" \
  -H "X-Splunk-Key: $SESSION_KEY" \
  -k
```

Response:
```json
{
  "success": true,
  "csv_file": "DR_BruteForce.csv",
  "headers": ["src_ip", "user", "comment"],
  "rows": [
    {"src_ip": "192.168.1.100", "user": "admin", "comment": "Internal IP"},
    {"src_ip": "192.168.1.101", "user": "user2", "comment": ""}
  ]
}
```

### 2. Save CSV Changes

Update rows in a CSV file:

```bash
curl -X POST \
  "https://your-splunk:8089/custom/wl_manager" \
  -H "X-Splunk-Key: $SESSION_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "action": "save_csv",
    "csv_file": "DR_BruteForce.csv",
    "app": "SA-ThreatIntel",
    "old_rows": [
      {"src_ip": "192.168.1.100", "user": "admin", "comment": "Old"}
    ],
    "new_rows": [
      {"src_ip": "192.168.1.100", "user": "admin", "comment": "Updated"}
    ],
    "comment": "Updated comment"
  }' \
  -k
```

### 3. Add a Row

Add a new row to a CSV:

```bash
curl -X POST \
  "https://your-splunk:8089/custom/wl_manager" \
  -H "X-Splunk-Key: $SESSION_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "action": "add_row",
    "csv_file": "DR_BruteForce.csv",
    "app": "SA-ThreatIntel",
    "old_rows": [],
    "new_rows": [
      {"src_ip": "10.0.0.0/8", "user": "internal", "comment": "Internal subnet"}
    ],
    "comment": "Whitelisting internal subnet"
  }' \
  -k
```

### 4. Remove Rows

Remove rows from a CSV:

```bash
curl -X POST \
  "https://your-splunk:8089/custom/wl_manager" \
  -H "X-Splunk-Key: $SESSION_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "action": "remove_rows",
    "csv_file": "DR_BruteForce.csv",
    "app": "SA-ThreatIntel",
    "old_rows": [
      {"src_ip": "192.168.1.100", "user": "admin"}
    ],
    "new_rows": [],
    "comment": "IP no longer needed in whitelist"
  }' \
  -k
```

### 5. Get Version History

Retrieve the version history for a CSV file:

```bash
curl -X GET \
  "https://your-splunk:8089/custom/wl_manager?action=get_versions&csv_file=DR_BruteForce.csv" \
  -H "X-Splunk-Key: $SESSION_KEY" \
  -k
```

Response:
```json
{
  "success": true,
  "csv_file": "DR_BruteForce.csv",
  "versions": [
    {
      "version_id": "1704067836",
      "timestamp": "24-02-2026 12:37:16",
      "row_count": 42,
      "analyst": "admin"
    },
    {
      "version_id": "1704067700",
      "timestamp": "24-02-2026 12:35:00",
      "row_count": 40,
      "analyst": "analyst1"
    }
  ]
}
```

### 6. Revert to Previous Version

Revert a CSV to a previous version:

```bash
curl -X POST \
  "https://your-splunk:8089/custom/wl_manager" \
  -H "X-Splunk-Key: $SESSION_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "action": "revert_csv",
    "csv_file": "DR_BruteForce.csv",
    "app": "SA-ThreatIntel",
    "version_id": "1704067700",
    "comment": "Reverting accidental changes"
  }' \
  -k
```

### 7. Submit for Approval

Submit bulk changes for admin approval:

```bash
curl -X POST \
  "https://your-splunk:8089/custom/wl_manager" \
  -H "X-Splunk-Key: $SESSION_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "action": "submit_approval",
    "action_type": "save_csv",
    "payload": {
      "csv_file": "DR_BruteForce.csv",
      "old_rows": [],
      "new_rows": [
        {"src_ip": "10.0.0.0/8", "user": "internal"}
      ]
    },
    "reason": "Adding internal subnet to whitelist per SOC request"
  }' \
  -k
```

## HTTP Status Codes

| Code | Meaning | Example |
|------|---------|---------|
| 200  | OK - Action succeeded | CSV fetched, saved, or modified successfully |
| 400  | Bad Request - Validation error | Missing required parameter, invalid filename |
| 401  | Unauthorized - Not authenticated | Session expired, no session key provided |
| 403  | Forbidden - Insufficient permissions | User lacks required role (one of `wl_superadmin`, `wl_admin`, `wl_analyst_editor`, `wl_analyst_viewer` — modern 4-tier — or the backward-compat aliases `wl_editor` / `wl_viewer`; see `default/authorize.conf`) |
| 404  | Not Found - Resource doesn't exist | CSV file not found, version not found |
| 429  | Too Many Requests - Limit exceeded | Daily edit limit exceeded |
| 500  | Server Error - Unexpected exception | Internal error (check Splunk logs) |

## Viewing the OpenAPI Specification

The full OpenAPI 3.0 specification is available in `openapi.yaml`. You can view and test it using:

### Swagger UI

1. Go to [https://editor.swagger.io](https://editor.swagger.io)
2. Click "File" → "Import URL"
3. Paste: `https://your-splunk/static/app/wl_manager/docs/api/openapi.yaml`
4. The spec will load with interactive documentation

Alternatively, use the Swagger UI Docker image:

```bash
docker run -p 8080:8080 -e SWAGGER_JSON=/spec/openapi.yaml \
  -v $(pwd)/openapi.yaml:/spec/openapi.yaml \
  swaggerapi/swagger-ui
```

Then visit http://localhost:8080

### ReDoc

1. Go to [https://redocly.github.io/redoc](https://redocly.github.io/redoc)
2. Paste the URL to your spec in the URL bar

### OpenAPI Spec Validator

Validate the spec syntax locally:

```bash
pip install openapi-spec-validator
openapi-spec-validator openapi.yaml
```

## Authentication Details

### Getting a Session Key

Use the Splunk REST API `/services/auth/login` endpoint:

```bash
SESSION_KEY=$(curl -s -k -u admin:password \
  https://your-splunk:8089/services/auth/login \
  -d 'username=admin&password=password' \
  | grep -oP '<sessionKey>\K[^<]+')

echo "Session Key: $SESSION_KEY"
```

### Passing the Session Key

In all subsequent requests, include the session key:

```bash
curl -H "X-Splunk-Key: $SESSION_KEY" \
  "https://your-splunk:8089/custom/wl_manager?action=get_rules" \
  -k
```

## RBAC Requirements

Different actions require different Splunk roles. The modern 4-tier
RBAC ships in `default/authorize.conf`; the older 2-tier aliases
(`wl_editor`, `wl_viewer`) still work because they import the new
roles automatically. See `docs/SECURITY_ARCHITECTURE.md` for the
full RBAC matrix.

| Action Category | Required Roles | Description |
|-----------------|----------------|-------------|
| Read (GET) | Any authenticated user (anyone with read access to `wl_audit`) | All authenticated users can read CSVs and audit trail |
| Write (`save_csv`, `add_row`, etc.) | `wl_analyst_editor` (or `wl_editor` alias) — also satisfied by `wl_admin` / `wl_superadmin` | Edit whitelists; subject to per-user daily limits + approval gates |
| Admin (`set_analyst_limits`, approve requests, manage trash) | `wl_admin` (or `wl_superadmin`) | Approve/reject requests, configure analyst limits, manage trash |
| Super-admin (`set_admin_limits`, lockdown control, factory reset) | `wl_superadmin` only | Admin-tier limit configuration, Emergency Lockdown activate/deactivate, factory reset |

## Error Handling

All error responses include a `success: false` flag and an `error` message:

```json
{
  "success": false,
  "error": "CSV file not found"
}
```

Some errors also include additional context:

```json
{
  "success": false,
  "error": "Daily limit exceeded: 10/10 edits used",
  "limit_type": "analyst_edits",
  "current": 10,
  "maximum": 10
}
```

Always check the `success` field before processing response data.

## Integration Examples

### Python Client

```python
import requests
import json

class WLClient:
    def __init__(self, splunk_url, session_key):
        self.base_url = f"{splunk_url}/custom/wl_manager"
        self.session_key = session_key
        self.headers = {"X-Splunk-Key": session_key}

    def get_csv_content(self, csv_file, app="wl_manager"):
        resp = requests.get(
            self.base_url,
            params={"action": "get_csv_content", "csv_file": csv_file, "app": app},
            headers=self.headers,
            verify=False
        )
        return resp.json()

    def save_csv(self, csv_file, old_rows, new_rows, comment, app="wl_manager"):
        resp = requests.post(
            self.base_url,
            json={
                "action": "save_csv",
                "csv_file": csv_file,
                "app": app,
                "old_rows": old_rows,
                "new_rows": new_rows,
                "comment": comment
            },
            headers=self.headers,
            verify=False
        )
        return resp.json()

# Usage
client = WLClient("https://your-splunk:8089", session_key)
content = client.get_csv_content("DR_Test.csv")
print(content)
```

## API Reference

For detailed documentation of all available actions, parameters, and responses, see the OpenAPI specification in `openapi.yaml`.

Quick navigation to common actions:

**CSV Operations:**
- `get_csv_content`: Fetch CSV data with headers and rows
- `save_csv`: Update CSV (with old_rows → new_rows diff)
- `add_row`: Add new rows
- `remove_rows`: Remove rows
- `revert_csv`: Revert to previous version
- `get_versions`: List version history

**Rule Management:**
- `create_rule`: Register new detection rule name
- `remove_rule`: Delete detection rule

**Admin Operations:**
- `set_daily_limits`: Configure analyst edit limits
- `get_daily_limits`: View limit settings
- `reset_daily_usage`: Clear analyst usage counters

**Approval Workflow:**
- `submit_approval`: Submit for approval
- `get_pending_approvals`: List pending requests
- `process_approval`: Approve/reject request

## Support

For issues, bugs, or feature requests, contact the Whitelist Manager development team.

---

**Last Updated:** 2026-04-02  
**API Version:** 1.0.0  
**Spec Format:** OpenAPI 3.0.0
