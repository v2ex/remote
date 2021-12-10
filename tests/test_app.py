import json
import os
import unittest
from typing import Any, Dict

from remote.app import AppENV, create_app


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
