import unittest
from src.validators import URLValidationError, validate_public_url

class URLValidationTests(unittest.TestCase):
    def test_accepts_public_http_url_without_dns_lookup(self):
        self.assertEqual(validate_public_url("https://example.com/news", resolve_dns=False), "https://example.com/news")

    def test_rejects_local_and_special_addresses(self):
        for url in ("http://127.0.0.1/a", "http://10.0.0.1/a", "http://[::1]/", "http://localhost/a", "file:///etc/passwd"):
            with self.subTest(url=url), self.assertRaises(URLValidationError):
                validate_public_url(url, resolve_dns=False)

    def test_rejects_credentials_and_non_web_port(self):
        for url in ("https://user:pass@example.com", "https://example.com:8080"):
            with self.subTest(url=url), self.assertRaises(URLValidationError):
                validate_public_url(url, resolve_dns=False)
