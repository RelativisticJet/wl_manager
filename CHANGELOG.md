# Changelog

All notable changes to this project will be documented in this file.

## Version 1.0.0 - 2025-03-20

### Features

- Initial release of Splunk Whitelist Manager
- Web-based interface for managing detection rule whitelists
- Support for 16+ detection rules (DR20, DR45, DR71, DR88, DR102, DR130, DR200, DR520, DR55, DR600, DR610, DR620, DR630, DR640, DR650, DR999)
- Role-based access control with wl_manager_admin, wl_manager_approver, and wl_manager_user roles
- Comprehensive audit trail logging all whitelist modifications
- Bulk operations for efficient whitelist management
- REST API for programmatic whitelist management
- Customizable rule mapping via rule_csv_map.csv
- Control panel for administrative tasks
- Full documentation and user guide

### Testing

- All 11 integration tests passing
- Tested on Splunk 8.x and 9.x
- Validated with 16+ detection rules
- Role-based access control verified
- Audit trail logging confirmed

### Known Limitations

- Requires Splunk Enterprise 7.3 or higher
- Lookup file modifications are immediate and not versioned
- Audit trail retention depends on audit index settings
