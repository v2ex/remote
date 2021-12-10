from unittest.mock import patch

import pyipip
from dns.exception import DNSException

from remote.blueprints.network import IPRecord
from tests.test_app import TestBase


class TestNetwork(TestBase):
    _test_domain = "example.com"
    _test_ip = "127.0.0.1"

    def test_ip(self):
        response = self.client.get("/ip")
        self.assertEqual(response.status_code, 200)

        _json_body = response.json
        self.assertIn("success", _json_body)
        self.assertEqual(_json_body["ip"], response.request.remote_addr)
        self.assertIn("ipv4", _json_body)
        self.assertIn("ipv6_available", _json_body)

    def test_ipip(self):
        ipdb_func = "remote.blueprints.network._get_ipdb"
        mock_func = "remote.blueprints.network.pyipip.IPIPDatabase.lookup"
        fake_ip_fields = "\t".join(map(str, range(len(IPRecord._fields) - 2)))
        with (
            patch(ipdb_func, return_value=pyipip.IPIPDatabase),
            patch(mock_func, return_value=fake_ip_fields),
        ):
            response = self.client.get(f"/ipip/{self._test_ip}")

        self.assertEqual(response.status_code, 200)

        _json_body = response.json
        self.assertIn("success", _json_body)
        self.assertIn("continent_code", _json_body)
        self.assertIn("cn_division_code", _json_body)
        self.assertEqual(set(_json_body.keys()), set(IPRecord._fields))

    def test_ipip_error_1(self):
        response = self.client.get("/ipip/FF:FF")

        self.assertEqual(response.status_code, 400)

        _json_body = response.json
        self.assertIn("IPv6", _json_body["message"])
        self.assertEqual(_json_body["status"], "error")
        self.assertFalse(_json_body["success"])

    def test_ipip_error_2(self):
        response = self.client.get("/ipip/FAKE_IP")

        self.assertEqual(response.status_code, 400)

        _json_body = response.json
        self.assertIn("Invalid", _json_body["message"])
        self.assertEqual(_json_body["status"], "error")
        self.assertFalse(_json_body["success"])

    def test_ipip_error_3(self):
        ipdb_func = "remote.blueprints.network._get_ipdb"
        with patch(ipdb_func, side_effect=Exception("Mock Exception")):
            response = self.client.get(f"/ipip/{self._test_ip}")

        self.assertEqual(response.status_code, 404)

        _json_body = response.json
        self.assertIn("not found", _json_body["message"])
        self.assertEqual(_json_body["status"], "error")
        self.assertFalse(_json_body["success"])

    def test_resolve(self):
        response = self.client.get(f"/dns/resolve?domain={self._test_domain}")
        self.assertEqual(response.status_code, 200)

        _json_body = response.json
        self.assertIn("nameservers", _json_body)
        self.assertIn("ttl", _json_body)
        self.assertIsInstance(_json_body["answers"], list)

    def test_resolve_error_1(self):
        response = self.client.get("/dns/resolve")
        self.assertEqual(response.status_code, 400)

        _json_body = response.json
        self.assertEqual("error", _json_body["status"])
        self.assertFalse(_json_body["success"])
        self.assertIn("missing", _json_body["message"])

    def test_resolve_error_2(self):
        mock_func = "remote.blueprints.network.dns.resolver.Resolver.resolve"
        with patch(mock_func, side_effect=DNSException("Mock Exception")):
            response = self.client.get(f"/dns/resolve?domain={self._test_domain}")
        self.assertEqual(response.status_code, 400)

        _json_body = response.json
        self.assertEqual("error", _json_body["status"])
        self.assertFalse(_json_body["success"])
        self.assertIn("Unable", _json_body["message"])
