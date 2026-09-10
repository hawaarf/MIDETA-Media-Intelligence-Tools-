import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


class ThreadsTrackerPageTests(unittest.TestCase):
    def test_tracker_page_has_filters_and_login_controls(self):
        page = Path(__file__).resolve().parents[1] / "pages" / "4_Threads_Tracker.py"
        app = AppTest.from_file(page)
        app.run(timeout=10)

        self.assertFalse(app.exception)
        self.assertEqual(app.text_input[0].label, "Keyword")
        self.assertEqual(
            [(widget.label, widget.value) for widget in app.selectbox],
            [
                ("Rentang waktu", "Recent (24 jam)"),
                ("Urutan hasil", "Engagement paling ramai"),
            ],
        )
        self.assertTrue(any(button.label == "Buka Sesi Threads" for button in app.button))
        self.assertTrue(any(button.label == "Cari Postingan Threads" for button in app.button))


if __name__ == "__main__":
    unittest.main()
