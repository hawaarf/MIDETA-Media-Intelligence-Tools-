# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import unittest
from unittest.mock import patch

from src.ui import _preserve_running_page_on_navigation


class UiNavigationTests(unittest.TestCase):
    def test_feature_links_open_in_new_tab_to_preserve_active_process(self):
        with patch("src.ui.st.html") as render_component:
            _preserve_running_page_on_navigation()

        script = render_component.call_args.args[0]
        self.assertIn('link.target = \'_blank\'', script)
        self.assertNotIn("event.preventDefault()", script)
        self.assertIn('data-testid="stSidebarNav"', script)
        self.assertIn('data-testid="stPageLink"', script)
        self.assertIn("new MutationObserver(markFeatureLinks)", script)
        render_component.assert_called_once_with(script, unsafe_allow_javascript=True)


if __name__ == "__main__":
    unittest.main()
