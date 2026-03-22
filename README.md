# Splunk Whitelist Manager

## Overview

The Splunk Whitelist Manager is a comprehensive, user-friendly Splunk application designed to streamline the management of detection rule whitelists across your security operations. This application enables security teams to efficiently review, approve, and manage whitelist entries for critical detection rules without requiring direct access to lookup files or advanced Splunk configuration knowledge.

Built with an intuitive web interface, role-based access controls, and comprehensive audit logging, the Whitelist Manager reduces operational friction while maintaining security and compliance requirements. Teams can quickly respond to false positives, manage exceptions, and track all whitelist changes through a centralized dashboard.

## Features

- **Multi-Rule Support**: Manage whitelists for 16+ detection rules including data exfiltration, brute force, privilege escalation, and more
- **Web-Based Interface**: Intuitive dashboard for viewing, filtering, and managing whitelist entries
- **Role-Based Access Control**: Assign permissions to managers, approvers, and viewers for controlled access
- **Audit Trail**: Complete logging of all whitelist modifications with user attribution and timestamps
- **Bulk Operations**: Add, remove, or modify multiple whitelist entries efficiently
- **CSV Lookup Integration**: Seamless integration with Splunk lookup files for real-time whitelist application
- **Search Integration**: View whitelist status directly in detection rule searches
- **Flexible Rule Mapping**: Customizable configuration to add new detection rules

## Prerequisites

- Splunk Enterprise 7.3 or higher (8.x and 9.x recommended)
- Admin access to Splunk instance for app installation
- Available disk space for lookup files and audit logs
- Network access to the Splunk web interface

## Installation

### Method 1: Via Splunk Web UI (Recommended)

1. Download the latest package from the Releases page
2. Log in to Splunk as an admin
3. Navigate to Manage Apps and select Install app from file
4. Click Choose File and select the wl_manager-1.0.0.spl package
5. Click Upload app and wait for installation to complete
6. Restart Splunk when prompted

### Method 2: Via Splunk CLI

bash
/opt/splunk/bin/splunk install app wl_manager-1.0.0.spl -auth admin:password
bash

Replace 'admin:password' with your actual credentials.

### Method 3: Manual Installation

1. Extract the app package: tar -xzf wl_manager-1.0.0.spl
2. Copy to Splunk apps directory: cp -r wl_manager SPLUNK_HOME/etc/apps/
3. Set proper permissions: chown -R splunk:splunk SPLUNK_HOME/etc/apps/wl_manager
4. Restart Splunk: SPLUNK_HOME/bin/splunk restart

## Configuration

### 1. Map Detection Rules

Edit the rule_csv_map.csv file to define which detection rules use which lookup files:

- Location: lookups/rule_csv_map.csv
- Format: rule_name,csv_lookup_file,description
- Example: DR20_whitelist,DR20_whitelist.csv,DNS Tunneling Detection

### 2. Assign User Roles and Capabilities

The app includes custom roles for access control:

- wl_manager_admin: Full access to manage all whitelists and settings
- wl_manager_approver: Can approve whitelist changes
- wl_manager_user: Can view and submit whitelist change requests

Assign roles in Settings menu or through your identity provider.

### 3. Verify Index Configuration

Ensure that your Splunk instance has an index for audit logs:

1. Go to Settings and select Indexes
2. Verify audit index exists (default Splunk index)
3. The Whitelist Manager logs changes to the audit index automatically

## Usage

### Accessing the Application

1. Log in to your Splunk instance
2. In the app picker, select Whitelist Manager
3. You will see the main dashboard with available detection rules

### Managing Whitelists

View Whitelist Entries:
- Select a detection rule from the dropdown
- Current whitelist entries display in a table
- Use filters to search for specific entries

Add Whitelist Entry:
- Click Add Entry button
- Fill in required fields (varies by rule type)
- Click Save to add the entry

Remove Whitelist Entry:
- Click the delete icon next to an entry
- Confirm deletion when prompted
- Change is logged and applied immediately

### Checking Audit Trail

Navigate to the Audit Trail tab to:
- View all whitelist changes with timestamps
- See which user made each change
- Review the action taken (add, remove, modify)
- Track entry details that were modified
- Export audit logs for compliance reporting

## Architecture

The Whitelist Manager consists of several key components:

### CSV Lookup Files
- Rule-specific CSV files in the lookups/ directory
- Format: CSV with whitelist entries
- Updated in real-time by the backend handler

### Web Interface
- React-based front-end for intuitive user experience
- Located in appserver/static/
- Dashboard, control panel, and audit trail views

### Backend Handler
- Python script (bin/wl_handler.py) processes whitelist changes
- Updates CSV lookup files
- Logs all operations to audit index
- Enforces role-based permissions

### Configuration Files
- app.conf: App metadata and version info
- restmap.conf: REST API endpoint definitions
- authorize.conf: Role-based access control rules
- props.conf: Lookup file properties
- rule_csv_map.csv: Detection rule to lookup file mappings

## Development

### Building the App

To build a deployable package from source:

bash
./scripts/package.sh
bash

Output: dist/wl_manager-VERSION.spl

### Testing

Validate the app package:

bash
./scripts/validate.sh
bash

Run integration tests:

bash
pytest tests/ -v
bash

### Modifying Detection Rules

To add a new detection rule to the Whitelist Manager:

1. Create a new CSV lookup file in lookups/ directory
2. Define column structure matching your rule requirements
3. Add entry to lookups/rule_csv_map.csv
4. Update bin/wl_handler.py if new field types needed
5. Rebuild and test the app package

## Troubleshooting

### App Not Appearing in App Picker
- Check app is installed in Manage Apps
- Verify app.conf is properly formatted
- Restart Splunk and clear browser cache

### Whitelist Changes Not Applying
- Verify the backend handler has proper permissions
- Check Splunk logs for Python errors in bin/wl_handler.py
- Ensure lookup file path in rule_csv_map.csv is correct
- Verify detection rule references the correct lookup file

### Permission Denied Errors
- Ensure user has appropriate wl_manager role assigned
- Check authorize.conf for correct role definitions
- Verify REST API endpoint permissions in restmap.conf

### Contact Support

For additional issues, check the documentation or open an issue on GitHub repository.

## License and Support

This application is provided as-is for use within your organization.
For support, questions, or contributions, please contact your team lead.
