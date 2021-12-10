import importlib.util
import unittest

from remote.app import create_app


class TestBase(unittest.TestCase):
    def setUp(self):
        self.test_config = self.load_example_config()
        self.app = create_app(config=self.test_config, name="test")
        self.client = self.app.test_client()

    def tearDown(self):
        ...

    @staticmethod
    def get_fixture_path(uri):
        return f"tests/fixtures/{uri}"

    @staticmethod
    def load_example_config() -> object:
        # load module from file
        spec = importlib.util.spec_from_file_location(
            "config", "remote/config.example.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # set extra config for testing
        module.TESTING = True
        module.DEBUG = True
        return module


class TestApp(TestBase):
    def test_config(self):
        self.assertEqual(self.app.testing, True)
        self.assertEqual(self.app.debug, True)
        self.assertIn("UID", self.app.config)
        self.assertIn("REGION", self.app.config)
        self.assertIn("COUNTRY", self.app.config)
