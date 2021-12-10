import json
import os
import unittest
from typing import Any, Dict

from remote.app import APP_ENV_NAME, AppENV, create_app


class TestBase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(name="test", env=AppENV.TEST)
        self.client = self.app.test_client()

    def tearDown(self):
        ...

    @staticmethod
    def get_fixture_path(uri):
        return f"tests/fixtures/{uri}"


class TestApp(TestBase):
    def test_config(self):
        self.assertEqual(self.app.testing, True)
        self.assertEqual(self.app.debug, True)
        self.assertIn("UID", self.app.config)
        self.assertIn("REGION", self.app.config)
        self.assertIn("COUNTRY", self.app.config)

    def test_config_from_env(self):
        test_env_configs: Dict[str, Any] = {
            "UID": "test_uid",
            "DEBUG": json.dumps(False),
            "region": "test_region",
        }
        os.environ.update(test_env_configs)

        app_2 = create_app(name="test2", env=AppENV.TEST)

        for k, v in test_env_configs.items():
            if k.isupper():
                self.assertEqual(app_2.config[k], v)
            else:
                self.assertNotEqual(app_2.config[k.upper()], v)

    def test_config_from_env_without_app_env(self):
        # Confirm the `APP_ENV` env is not set, otherwise the app will use it.
        os.unsetenv(APP_ENV_NAME)

        test_env_configs: Dict[str, Any] = {
            "UID": "test_uid_2",
            "DEBUG": json.dumps(True),
            "region": "test_region_2",
        }
        os.environ.update(test_env_configs)

        app_3 = create_app(name="test3")

        for k, v in test_env_configs.items():
            if k.isupper():
                self.assertEqual(app_3.config[k], v)
            else:
                self.assertNotEqual(app_3.config[k.upper()], v)
