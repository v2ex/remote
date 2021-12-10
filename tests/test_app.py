import unittest

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
