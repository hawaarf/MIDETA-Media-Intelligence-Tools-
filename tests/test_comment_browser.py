import unittest
from unittest.mock import MagicMock, patch

from src.comment_browser import CommentBrowserCollector
from src.models import FieldStatus, PublicComment


class CommentBrowserTests(unittest.TestCase):
    def test_x_dom_rows_are_converted_without_the_target_status(self):
        collector = CommentBrowserCollector("X")
        rows = [
            {"href": "https://x.com/pemilik/status/100", "author": "pemilik", "comment": "Post utama"},
            {
                "href": "https://x.com/ayu/status/101",
                "author": "ayu",
                "comment": "Komentar langsung",
                "date": "2026-09-03T03:00:00.000Z",
                "likes": "15 Likes",
                "replies": "1 Reply",
                "context": "Replying to @pemilik",
            },
            {
                "href": "https://x.com/bima/status/102",
                "author": "bima",
                "comment": "Balasan komentar",
                "likes": "4 Likes",
                "replies": "",
                "context": "Replying to @ayu",
            },
        ]
        with patch.object(collector, "_x_dom_rows", return_value=rows):
            comments = collector._dom_comments("https://x.com/pemilik/status/100")

        self.assertEqual([comment.author for comment in comments], ["ayu", "bima"])
        self.assertEqual([comment.comment_type for comment in comments], ["parent", "reply"])
        self.assertEqual(comments[0].likes, 15)
        self.assertEqual(comments[0].reply_count, 1)

    def test_threads_dom_rows_are_converted_without_the_target_post(self):
        collector = CommentBrowserCollector("Threads")
        rows = [
            {
                "code": "Target123",
                "author": "pemilik",
                "comment": "Posting utama",
                "likes": "10",
                "replies": "2",
                "comment_type": "parent",
            },
            {
                "code": "Comment456",
                "author": "komentator",
                "comment": "Komentar publik",
                "date": "2026-09-03T01:02:03.000Z",
                "likes": "Like 1.2K",
                "replies": "Comment 7",
                "comment_type": "parent",
            },
            {
                "code": "Reply789",
                "author": "pemilik",
                "comment": "Balasan publik",
                "likes": "",
                "replies": "",
                "comment_type": "reply",
            },
        ]
        with patch.object(collector, "_threads_dom_rows", return_value=rows) as dom_rows:
            comments = collector._dom_comments(
                "https://www.threads.com/@pemilik/post/Target123"
            )

        dom_rows.assert_called_once_with("Target123")
        self.assertEqual([comment.comment for comment in comments], ["Komentar publik", "Balasan publik"])
        self.assertEqual(comments[0].likes, 1_200)
        self.assertEqual(comments[0].reply_count, 7)
        self.assertEqual(comments[1].comment_type, "reply")

    def test_public_threads_collection_does_not_require_login_first(self):
        collector = CommentBrowserCollector("Threads")
        driver = MagicMock()
        driver.window_handles = ["window"]
        driver.current_url = "https://www.threads.com/@pemilik/post/Target123"
        driver.page_source = "<html></html>"
        collector.driver = driver
        public_comment = PublicComment(
            author="komentator",
            comment="Terbaca tanpa login",
            source_url=driver.current_url,
        )
        connector = MagicMock()
        connector._platform_comments.return_value = []

        with (
            patch("src.comment_browser.get_platform_connector", return_value=connector),
            patch.object(collector, "_wait_for_page"),
            patch.object(collector, "_load_conversation"),
            patch.object(collector, "_dom_comments", return_value=[public_comment]),
            patch.object(collector, "is_logged_in", side_effect=AssertionError("login should be optional")),
        ):
            result = collector.collect(driver.current_url)

        self.assertEqual(result.status, FieldStatus.AVAILABLE)
        self.assertEqual(result.comments[0].comment, "Terbaca tanpa login")

    def test_login_check_opens_threads_domain_for_saved_profile(self):
        collector = CommentBrowserCollector("Threads")
        driver = MagicMock()
        driver.window_handles = ["window"]
        driver.current_url = "data:,"
        driver.get_cookies.return_value = [{"name": "sessionid", "value": "saved-session"}]
        collector.driver = driver

        with patch.object(collector, "_wait_for_page"):
            self.assertTrue(collector.is_logged_in())

        driver.get.assert_called_once_with("https://www.threads.com/login/")

    def test_open_login_reuses_an_active_saved_session(self):
        collector = CommentBrowserCollector("Threads")
        driver = MagicMock()
        driver.window_handles = ["window"]
        collector.driver = driver

        with (
            patch.object(collector, "_wait_for_page"),
            patch.object(collector, "is_logged_in", return_value=True) as login_check,
        ):
            session_active = collector.open_login()

        self.assertTrue(session_active)
        driver.get.assert_called_once_with("https://www.threads.com/")
        login_check.assert_called_once_with(open_platform=False)

    def test_open_login_only_shows_login_when_saved_session_is_missing(self):
        collector = CommentBrowserCollector("Threads")
        driver = MagicMock()
        driver.window_handles = ["window"]
        collector.driver = driver

        with (
            patch.object(collector, "_wait_for_page"),
            patch.object(collector, "is_logged_in", return_value=False),
        ):
            session_active = collector.open_login()

        self.assertFalse(session_active)
        self.assertEqual(
            [call.args[0] for call in driver.get.call_args_list],
            ["https://www.threads.com/", "https://www.threads.com/login/"],
        )


if __name__ == "__main__":
    unittest.main()
