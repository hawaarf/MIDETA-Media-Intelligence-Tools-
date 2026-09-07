import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class CommentPageTests(unittest.TestCase):
    def test_triple_screen_keeps_platform_inputs_and_results_separate(self):
        page = Path(__file__).resolve().parents[1] / "pages" / "2_Comment_Scrapper.py"
        with patch("src.database.add_history", return_value=1):
            app = AppTest.from_file(page)
            app.run(timeout=10)
            app.get("button_group")[0].set_value("Triple Screen").run(timeout=10)

            self.assertEqual(
                [(widget.label, widget.value) for widget in app.selectbox],
                [
                    ("Platform kiri", "Facebook"),
                    ("Platform tengah", "Threads"),
                    ("Platform kanan", "X"),
                ],
            )
            urls = [
                "https://www.facebook.com/akun/posts/1",
                "https://www.threads.net/@akun/post/abc",
                "https://x.com/akun/status/1",
            ]
            for widget, url in zip(app.text_area, urls):
                widget.set_value(url)
            for widget in app.checkbox:
                widget.set_value(True)
            next(button for button in app.button if button.label == "Mulai Tiga Proses").click().run(timeout=10)

        self.assertFalse(app.exception)
        self.assertEqual(len(app.success), 3)
        self.assertEqual([metric.value for metric in app.metric if metric.label == "Komentar"], ["2", "2", "2"])


if __name__ == "__main__":
    unittest.main()
