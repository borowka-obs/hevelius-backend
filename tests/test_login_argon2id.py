import json
import os
import unittest

from argon2 import PasswordHasher, Type

from hevelius import db
from tests.dbtest import use_repository

from hevelius.api import app
from hevelius.passwords import password_hasher  # noqa: E402


class TestLoginArgon2id(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.client.testing = True

    @use_repository(load_test_data=None)
    def test_lazy_migration_from_md5(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]

        plaintext_password = "correct horse battery staple"
        # Precomputed MD5 hash of "correct horse battery staple"
        legacy_md5 = "9cc2ae8a1ba7a93da39b46fc1019c481"
        login = "legacy_user"

        cnx = db.connect(config)
        db.run_query(
            cnx,
            """
            INSERT INTO users (user_id, login, pass, firstname, lastname, share, phone, email,
                                permissions, aavso_id, pass_d)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                200,
                login,
                "pass",
                "Legacy",
                "User",
                1.0,
                "",
                "legacy@example.com",
                1,
                "AAVSO",
                legacy_md5.upper(),  # ensure case-insensitive compare
            ),
        )
        cnx.close()

        response = self.client.post(
            "/api/login",
            data=json.dumps({"username": login, "password": plaintext_password}),
            headers={"Content-Type": "application/json"},
        )
        data = json.loads(response.data)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(data["status"])
        self.assertIn("token", data)

        cnx = db.connect(config)
        pass_d_after = db.run_query(
            cnx, "SELECT pass_d FROM users WHERE user_id=%s", (200,)
        )[0][0]
        cnx.close()

        self.assertTrue(isinstance(pass_d_after, str))
        self.assertTrue(pass_d_after.startswith("$argon2id$"))

        # Clean up to match other tests' behavior.
        os.environ.pop("HEVELIUS_DB_NAME")

    @use_repository(load_test_data=None)
    def test_rehash_when_argon2_params_are_weak(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]

        plaintext_password = "super secret password"
        login = "weak_argon2_user"

        weak_hasher = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1, type=Type.ID)
        weak_hash = weak_hasher.hash(plaintext_password)

        cnx = db.connect(config)
        db.run_query(
            cnx,
            """
            INSERT INTO users (user_id, login, pass, firstname, lastname, share, phone, email,
                                permissions, aavso_id, pass_d)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                201,
                login,
                "pass",
                "Weak",
                "Argon2",
                1.0,
                "",
                "weak@example.com",
                1,
                "AAVSO",
                weak_hash,
            ),
        )
        cnx.close()

        self.assertTrue(password_hasher.check_needs_rehash(weak_hash))

        response = self.client.post(
            "/api/login",
            data=json.dumps({"username": login, "password": plaintext_password}),
            headers={"Content-Type": "application/json"},
        )
        data = json.loads(response.data)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(data["status"])

        cnx = db.connect(config)
        pass_d_after = db.run_query(cnx, "SELECT pass_d FROM users WHERE user_id=%s", (201,))[0][0]
        cnx.close()

        self.assertTrue(isinstance(pass_d_after, str))
        self.assertTrue(pass_d_after.startswith("$argon2id$"))
        self.assertNotEqual(pass_d_after, weak_hash)

        os.environ.pop("HEVELIUS_DB_NAME")
