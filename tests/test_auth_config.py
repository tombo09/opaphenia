import json
import os
import subprocess
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))


class AuthConfigurationTests(unittest.TestCase):
    def run_config(self, **environment):
        env = os.environ.copy()
        for name in (
            "APP_ENV",
            "SECRET_KEY",
            "COOKIE_SECURE",
            "COOKIE_SAMESITE",
            "TRUST_PROXY_HEADERS",
            "TRUSTED_PROXIES",
        ):
            env.pop(name, None)
        env.update(environment)
        return subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import json; from app import config; "
                    "print(json.dumps({"
                    "'env': config.APP_ENV, "
                    "'secret': config.SECRET_KEY, "
                    "'secure': config.COOKIE_SECURE, "
                    "'httponly': config.COOKIE_HTTPONLY, "
                    "'samesite': config.COOKIE_SAMESITE, "
                    "'path': config.COOKIE_PATH}))"
                ),
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_development_defaults_are_workable_and_explicitly_insecure(self):
        result = self.run_config()
        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads(result.stdout)
        self.assertEqual(config["env"], "development")
        self.assertTrue(config["secret"].startswith("development-only-"))
        self.assertFalse(config["secure"])
        self.assertTrue(config["httponly"])
        self.assertEqual(config["samesite"], "lax")
        self.assertEqual(config["path"], "/")

    def test_production_rejects_missing_placeholder_and_weak_secrets(self):
        for secret in (None, "CHANGE_ME_IN_PROD", "x" * 64, "too-short"):
            environment = {"APP_ENV": "production"}
            if secret is not None:
                environment["SECRET_KEY"] = secret
            with self.subTest(secret=secret):
                result = self.run_config(**environment)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(secret or "not-present", result.stderr)

    def test_production_uses_secure_cookie_defaults(self):
        result = self.run_config(
            APP_ENV="production",
            SECRET_KEY="correct-horse-battery-staple-production-key-2026",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads(result.stdout)
        self.assertTrue(config["secure"])
        self.assertTrue(config["httponly"])
        self.assertEqual(config["samesite"], "lax")
        self.assertEqual(config["path"], "/")

    def test_production_rejects_insecure_cookie_override(self):
        result = self.run_config(
            APP_ENV="production",
            SECRET_KEY="correct-horse-battery-staple-production-key-2026",
            COOKIE_SECURE="false",
        )
        self.assertNotEqual(result.returncode, 0)

    def test_samesite_none_requires_secure_cookie(self):
        result = self.run_config(
            APP_ENV="development",
            COOKIE_SAMESITE="none",
        )
        self.assertNotEqual(result.returncode, 0)

    def test_login_and_logout_cookie_attributes_match(self):
        env = os.environ.copy()
        env.pop("COOKIE_SECURE", None)
        env.pop("COOKIE_SAMESITE", None)
        env.update(
            {
                "APP_ENV": "production",
                "SECRET_KEY": "correct-horse-battery-staple-production-key-2026",
                "ETH_PK": "0x" + "1" * 64,
            }
        )
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from fastapi import Response; "
                    "from app.routers.auth import _set_auth_cookie, _clear_auth_cookie; "
                    "a=Response(); _set_auth_cookie(a, 'token'); "
                    "b=Response(); _clear_auth_cookie(b); "
                    "print(a.headers['set-cookie']); print(b.headers['set-cookie'])"
                ),
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        created, deleted = result.stdout.strip().splitlines()
        for header in (created, deleted):
            self.assertIn("HttpOnly", header)
            self.assertIn("Path=/", header)
            self.assertIn("SameSite=lax", header)
            self.assertIn("Secure", header)
        self.assertIn("Max-Age=3600", created)
        self.assertIn("Max-Age=0", deleted)

    def test_proxy_mode_requires_valid_trusted_proxy_configuration(self):
        for proxies in (None, "not-an-ip", "127.0.0.1,"):
            environment = {"TRUST_PROXY_HEADERS": "true"}
            if proxies is not None:
                environment["TRUSTED_PROXIES"] = proxies
            with self.subTest(proxies=proxies):
                result = self.run_config(**environment)
                self.assertNotEqual(result.returncode, 0)

        result = self.run_config(
            TRUST_PROXY_HEADERS="true",
            TRUSTED_PROXIES="127.0.0.1,::1,10.0.0.0/8",
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
