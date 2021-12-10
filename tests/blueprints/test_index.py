from tests.test_app import TestBase


class TestIndex(TestBase):
    def test_home(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

        self.assertEqual(response.json, {})

    def test_ping(self):
        response = self.client.get("/ping")
        self.assertEqual(response.status_code, 200)

        _json_body = response.json
        self.assertIn("status", _json_body)
        self.assertIn("success", _json_body)
        self.assertEqual("pong", _json_body["message"])

    def test_hello(self):
        response = self.client.get("/hello")
        self.assertEqual(response.status_code, 200)

        _json_body = response.json
        self.assertIn("region", _json_body)
        self.assertEqual(True, _json_body["success"])
