"""
Tests that the OpenAPI spec matches the actual API contract.

Runs quickly: no DB or auth required. Validates spec structure and
one live response (GET /api/version) against the spec.
"""

import os
import unittest
import yaml

# Import app after potential test env setup
from heveliusbackend.app import app


def load_spec():
    """Load OpenAPI spec from api/openapi.yaml."""
    spec_path = os.path.join(os.path.dirname(__file__), "..", "api", "openapi.yaml")
    with open(os.path.normpath(spec_path)) as f:
        return yaml.safe_load(f)


class TestOpenAPISpec(unittest.TestCase):
    """OpenAPI spec structure and consistency."""

    def setUp(self):
        self.spec = load_spec()

    def test_spec_loads_and_has_required_structure(self):
        self.assertIn("openapi", self.spec)
        self.assertIn("paths", self.spec)
        self.assertIn("components", self.spec)
        self.assertIn("schemas", self.spec["components"])

    def test_expected_paths_exist(self):
        paths = set(self.spec["paths"].keys())
        expected = {
            "/api/version",
            "/api/login",
            "/api/task-add",
            "/api/tasks",
            "/api/task-get",
            "/api/task-update",
            "/api/night-plan",
            "/api/scopes",
            "/api/filters",
            "/api/filters/{filter_id}",
            "/api/sensors",
            "/api/sensors/{sensor_id}",
            "/api/projects",
            "/api/projects/{project_id}",
            "/api/catalogs/search",
            "/api/catalogs/list",
        }
        self.assertEqual(paths, expected, "OpenAPI paths should match implemented routes")

    def test_version_response_schema_exists(self):
        version_path = self.spec["paths"]["/api/version"]
        get_op = version_path.get("get")
        self.assertIsNotNone(get_op, "GET /api/version must be defined")
        resp = get_op["responses"].get("200")
        self.assertIsNotNone(resp)
        content = resp.get("content", {}).get("application/json", {})
        schema = content.get("schema", {})
        self.assertIn("$ref", schema)
        self.assertIn("VersionResponse", schema["$ref"])

    def test_tasks_list_schema_has_pagination_fields(self):
        tasks_list = self.spec["components"]["schemas"]["TasksList"]
        props = set(tasks_list.get("properties", {}).keys())
        self.assertIn("tasks", props)
        self.assertIn("total", props)
        self.assertIn("page", props)
        self.assertIn("per_page", props)
        self.assertIn("pages", props)

    def test_telescopes_list_schema_has_telescopes_key(self):
        scopes = self.spec["components"]["schemas"]["TelescopesList"]
        props = set(scopes.get("properties", {}).keys())
        self.assertIn("telescopes", props)


class TestVersionResponseMatchesSpec(unittest.TestCase):
    """Live check: /api/version response matches OpenAPI VersionResponse."""

    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True
        self.spec = load_spec()

    def test_version_response_matches_spec(self):
        response = self.app.get("/api/version")
        self.assertEqual(response.status_code, 200, "GET /api/version should return 200")

        data = response.get_json()
        self.assertIsInstance(data, dict)

        version_schema = self.spec["components"]["schemas"]["VersionResponse"]
        required = set(version_schema.get("properties", {}).keys())
        for key in required:
            self.assertIn(key, data, f"Version response must include '{key}' (per OpenAPI)")
        self.assertIsInstance(data["version"], str, "version must be a string per spec")


if __name__ == "__main__":
    unittest.main()
