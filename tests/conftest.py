"""
Pytest configuration for Hevelius tests.

This module provides session-scoped fixtures for database setup and cleanup.
"""

import pytest
from tests.dbtest import cleanup_template_database


@pytest.fixture(scope="session", autouse=True)
def cleanup_after_tests():
    """Clean up template database after all tests complete."""
    # Setup: nothing to do, template is created lazily
    yield
    # Teardown: clean up the template database
    cleanup_template_database()
