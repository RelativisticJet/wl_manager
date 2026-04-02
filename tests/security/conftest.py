"""Pytest fixtures for security tests.

Provides:
- xss_payloads: OWASP XSS attack vectors
- path_traversal_payloads: Path traversal test cases
- injection_payloads: SQL/command injection payloads
- rbac_matrix: Role × action access matrix
"""

import json
import os
import pytest


@pytest.fixture
def xss_payloads():
    """Load XSS payloads from fixtures."""
    fixture_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "xss_payloads.json"
    )
    with open(fixture_path) as f:
        return json.load(f)["payloads"]


@pytest.fixture
def path_traversal_payloads():
    """Load path traversal payloads from fixtures."""
    fixture_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "path_traversal_payloads.json"
    )
    with open(fixture_path) as f:
        return json.load(f)["payloads"]


@pytest.fixture
def injection_payloads():
    """Load injection payloads from fixtures."""
    fixture_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "injection_payloads.json"
    )
    with open(fixture_path) as f:
        return json.load(f)["payloads"]


@pytest.fixture
def rbac_matrix():
    """Load RBAC matrix from fixtures."""
    fixture_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "rbac_matrix.json"
    )
    with open(fixture_path) as f:
        return json.load(f)["matrix"]
