import os
import unittest
from unittest.mock import patch

from src.runtime import browser_sessions_available


class RuntimeTests(unittest.TestCase):
    def test_local_streamlit_url_allows_browser_sessions(self):
        self.assertTrue(browser_sessions_available("http://localhost:8501/Comment_Scrapper"))
        self.assertTrue(browser_sessions_available("http://127.0.0.1:8501"))

    def test_deployed_url_disables_local_browser_sessions(self):
        self.assertFalse(browser_sessions_available("https://mideta.streamlit.app/Comment_Scrapper"))

    def test_environment_override_supports_self_hosted_desktop(self):
        with patch.dict(os.environ, {"MIDETA_BROWSER_SESSIONS": "enabled"}):
            self.assertTrue(browser_sessions_available("https://mideta.example.com"))
        with patch.dict(os.environ, {"MIDETA_BROWSER_SESSIONS": "disabled"}):
            self.assertFalse(browser_sessions_available("http://localhost:8501"))


if __name__ == "__main__":
    unittest.main()
