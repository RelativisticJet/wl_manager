"""
Mock splunk.rest module for offline unit testing.

This stub provides a mock simpleRequest() function that allows tests to verify
Splunk API calls without needing a live container.
"""

from typing import Optional, Dict, Tuple, Any


def simpleRequest(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body: Optional[str] = None,
    raiseException: bool = True,
    **kwargs: Any
) -> Tuple[int, str]:
    """
    Mock implementation of splunk.rest.simpleRequest.

    Args:
        url: API endpoint URL (e.g., "/services/authentication/current-context")
        method: HTTP method ("GET", "POST", etc.)
        headers: HTTP headers (including auth)
        body: Request body
        raiseException: If True, raise on 4xx/5xx (mocked behavior)
        **kwargs: Additional parameters (ignored)

    Returns:
        (status_code, response_body) tuple

    Behavior (for phase 1 tests):
    - /services/authentication/current-context: Returns mock current user (admin)
    - /services/search/v2/searches: Returns empty search list (for admin discovery)
    - Other endpoints: Return 404 by default (tests override via monkeypatch)
    """
    # Default responses for common endpoints
    if url.endswith("/services/authentication/current-context"):
        return (200, '{"entry": [{"content": {"username": "admin"}}]}')

    elif url.endswith("/services/search/v2/searches"):
        return (200, '{"entries": []}')

    # Default: not found
    return (404, '{"messages": [{"type": "ERROR", "text": "Mock endpoint not found"}]}')
