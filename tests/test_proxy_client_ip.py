import unittest
from ipaddress import ip_network
from unittest.mock import patch

from starlette.requests import Request

from app import limiter


def make_request(peer: str, headers=()) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [
                (name.lower().encode(), value.encode()) for name, value in headers
            ],
            "client": (peer, 12345),
        }
    )


class TrustedProxyClientIpTests(unittest.TestCase):
    def client_ip(self, peer, headers, proxies):
        with (
            patch.object(limiter, "TRUST_PROXY_HEADERS", True),
            patch.object(limiter, "TRUSTED_PROXIES", proxies),
        ):
            return limiter.get_client_ip(make_request(peer, headers))

    def test_spoofed_headers_from_untrusted_peer_are_ignored(self):
        result = self.client_ip(
            "203.0.113.9",
            [("X-Forwarded-For", "198.51.100.1")],
            (),
        )
        self.assertEqual(result, "203.0.113.9")

    def test_header_from_trusted_proxy_is_accepted(self):
        result = self.client_ip(
            "127.0.0.1",
            [("CF-Connecting-IP", "198.51.100.20")],
            (ip_network("127.0.0.1"),),
        )
        self.assertEqual(result, "198.51.100.20")

    def test_malformed_forwarding_headers_are_ignored_safely(self):
        result = self.client_ip(
            "127.0.0.1",
            [
                ("X-Forwarded-For", "garbage, 198.51.100.20"),
                ("CF-Connecting-IP", "also-garbage"),
            ],
            (ip_network("127.0.0.1"),),
        )
        self.assertEqual(result, "127.0.0.1")

    def test_trusted_proxy_cidr_is_supported(self):
        result = self.client_ip(
            "10.2.3.4",
            [("X-Forwarded-For", "198.51.100.30")],
            (ip_network("10.0.0.0/8"),),
        )
        self.assertEqual(result, "198.51.100.30")

    def test_multiple_hops_select_first_untrusted_from_right(self):
        result = self.client_ip(
            "10.0.0.2",
            [("X-Forwarded-For", "192.0.2.99, 198.51.100.40, 10.0.0.1")],
            (ip_network("10.0.0.0/8"),),
        )
        self.assertEqual(result, "198.51.100.40")

    def test_disabled_mode_always_uses_socket_peer(self):
        with patch.object(limiter, "TRUST_PROXY_HEADERS", False):
            result = limiter.get_client_ip(
                make_request(
                    "203.0.113.10",
                    [("X-Forwarded-For", "198.51.100.50")],
                )
            )
        self.assertEqual(result, "203.0.113.10")


if __name__ == "__main__":
    unittest.main()
