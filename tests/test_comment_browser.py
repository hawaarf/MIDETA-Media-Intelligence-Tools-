import unittest
from unittest.mock import MagicMock, patch

from src.comment_browser import CommentBrowserCollector
from src.models import FieldStatus, PublicComment


class CommentBrowserTests(unittest.TestCase):
    def test_facebook_login_uses_its_own_saved_profile(self):
        collector = CommentBrowserCollector("Facebook")
        driver = MagicMock()
        driver.window_handles = ["window"]
        driver.current_url = "data:,"
        driver.get_cookies.return_value = [{"name": "c_user", "value": "1000123456789"}]
        collector.driver = driver

        with patch.object(collector, "_wait_for_page"):
            self.assertTrue(collector.is_logged_in())

        driver.get.assert_called_once_with("https://www.facebook.com/login/")

    def test_facebook_dom_rows_are_converted_to_parent_and_reply(self):
        collector = CommentBrowserCollector("Facebook")
        rows = [
            {
                "code": "1001",
                "author": "Ayu",
                "comment": "Komentar utama",
                "date": "3 h",
                "likes": "15 reactions",
                "replies": "View 4 replies",
                "comment_type": "parent",
            },
            {
                "code": "1002",
                "author": "Bima",
                "comment": "Balasan komentar",
                "date": "2 h",
                "likes": "2 likes",
                "replies": "",
                "comment_type": "reply",
            },
        ]

        with patch("src.comment_browser.relative_social_date_iso", return_value="2026-09-11"):
            comments = collector._dom_comments(
                "https://www.facebook.com/100/posts/200",
                rows,
            )

        self.assertEqual([comment.author for comment in comments], ["Ayu", "Bima"])
        self.assertEqual([comment.comment_type for comment in comments], ["parent", "reply"])
        self.assertEqual(comments[0].likes, 15)
        self.assertEqual(comments[0].reply_count, 4)
        self.assertEqual(comments[0].commented_at, "2026-09-11")

    def test_facebook_author_does_not_include_relative_time(self):
        collector = CommentBrowserCollector("Facebook")
        rows = [
            {
                "code": "1001",
                "author": "Ilham Adi seminggu yang lalu",
                "comment": "Komentar utama",
                "date": "",
                "likes": "",
                "replies": "",
                "comment_type": "parent",
            }
        ]

        with patch("src.comment_browser.relative_social_date_iso", return_value="2026-09-04") as relative_date:
            comments = collector._dom_comments(
                "https://www.facebook.com/100/posts/200",
                rows,
            )

        self.assertEqual(comments[0].author, "Ilham Adi")
        self.assertEqual(comments[0].commented_at, "2026-09-04")
        relative_date.assert_called_once_with("seminggu yang lalu")

    def test_duplicate_dom_comment_enriches_public_like_reply_and_type(self):
        url = "https://www.facebook.com/100/posts/200"
        public = PublicComment(
            author="Ayu",
            comment="Komentar yang sama",
            likes=0,
            reply_count=0,
            comment_type="parent",
            source_url=url,
        )
        dom = PublicComment(
            author="Ayu",
            comment="Komentar yang sama",
            likes=17,
            reply_count=4,
            comment_type="reply",
            source_url=url,
        )

        merged = CommentBrowserCollector._merge_comments([public], [dom])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].likes, 17)
        self.assertEqual(merged[0].reply_count, 4)
        self.assertEqual(merged[0].comment_type, "reply")

    def test_virtualized_facebook_reply_does_not_change_back_to_parent(self):
        stored = {"1002": {"code": "1002", "comment": "Balasan", "comment_type": "reply"}}

        CommentBrowserCollector._merge_thread_rows(
            stored,
            [{"code": "1002", "comment": "Balasan", "comment_type": "parent", "likes": "2 reactions"}],
        )

        self.assertEqual(stored["1002"]["comment_type"], "reply")
        self.assertEqual(stored["1002"]["likes"], "2 reactions")

    def test_facebook_collection_merges_public_payload_and_loaded_dom_comments(self):
        collector = CommentBrowserCollector("Facebook")
        url = "https://www.facebook.com/100057414910274/posts/1558872422703240"
        driver = MagicMock()
        driver.window_handles = ["window"]
        driver.current_url = url
        driver.page_source = "<html></html>"
        collector.driver = driver
        initial = PublicComment(author="Ayu", comment="Komentar awal", source_url=url)
        additional = PublicComment(author="Bima", comment="Komentar setelah dimuat", source_url=url)
        connector = MagicMock()
        connector._platform_comments.return_value = [initial]

        with (
            patch("src.comment_browser.get_platform_connector", return_value=connector),
            patch.object(collector, "_wait_for_page"),
            patch.object(collector, "_prepare_facebook_comments") as prepare,
            patch.object(collector, "_load_conversation", return_value=[{"code": "1002"}]) as loader,
            patch.object(collector, "_dom_comments", return_value=[additional]) as dom_comments,
        ):
            result = collector.collect(url)

        prepare.assert_called_once_with()
        loader.assert_called_once_with(
            "",
            url,
            max_comments=2_000,
            progress_callback=None,
        )
        dom_comments.assert_called_once_with(url, [{"code": "1002"}])
        self.assertEqual(
            [comment.comment for comment in result.comments],
            ["Komentar awal", "Komentar setelah dimuat"],
        )

    def test_facebook_short_reel_link_waits_for_permalink_before_collecting(self):
        collector = CommentBrowserCollector("Facebook")
        short_url = "https://www.facebook.com/share/r/1Example/"
        permalink = "https://www.facebook.com/reel/1090418136855776"
        driver = MagicMock()
        driver.window_handles = ["window"]
        driver.current_url = permalink
        driver.page_source = "<html></html>"
        collector.driver = driver
        connector = MagicMock()
        connector._platform_comments.return_value = []
        visible = PublicComment(author="Ayu", comment="Komentar Reel", source_url=permalink)

        with (
            patch("src.comment_browser.get_platform_connector", return_value=connector),
            patch.object(collector, "_wait_for_page"),
            patch.object(collector, "_prepare_facebook_comments") as prepare,
            patch.object(collector, "_load_conversation", return_value=[{"code": "1"}]) as loader,
            patch.object(collector, "_dom_comments", return_value=[visible]),
            patch("src.comment_browser.time.sleep"),
        ):
            result = collector.collect(short_url)

        driver.get.assert_called_once_with(short_url)
        prepare.assert_called_once_with()
        loader.assert_called_once_with(
            "",
            permalink,
            max_comments=2_000,
            progress_callback=None,
        )
        self.assertEqual(result.url, permalink)
        self.assertEqual(result.comments[0].comment, "Komentar Reel")

    def test_threads_loader_keeps_rows_collected_before_dom_virtualization(self):
        collector = CommentBrowserCollector("Threads")
        collector.END_STABLE_ROUNDS = 2
        collector.THREADS_MAX_SCROLL_ROUNDS = 5
        driver = MagicMock()
        driver.window_handles = ["window"]
        driver.execute_script.side_effect = [
            {"reachedEnd": False, "clicked": 0, "scrollY": 100, "height": 1_000},
            {"reachedEnd": True, "clicked": 0, "scrollY": 200, "height": 1_200},
            {"reachedEnd": True, "clicked": 0, "scrollY": 200, "height": 1_200},
        ]
        collector.driver = driver
        first = {"code": "Comment1", "author": "ayu", "comment": "Komentar pertama"}
        second = {"code": "Comment2", "author": "bima", "comment": "Komentar berikutnya"}
        snapshots = [
            [{"code": "Target123", "is_target": True}, first],
            [{"code": "Target123", "is_target": True}, first, second],
            [{"code": "Target123", "is_target": True}, second],
            [{"code": "Target123", "is_target": True}, second],
            [{"code": "Target123", "is_target": True}, second],
            [{"code": "Target123", "is_target": True}, second],
        ]

        with (
            patch.object(collector, "_threads_dom_rows", side_effect=snapshots),
            patch("src.comment_browser.time.sleep"),
        ):
            rows = collector._load_conversation("Target123")

        self.assertEqual([row["code"] for row in rows], ["Target123", "Comment1", "Comment2"])

    def test_browser_collection_stops_at_two_thousand_comments_and_reports_progress(self):
        collector = CommentBrowserCollector("Threads")
        driver = MagicMock()
        driver.window_handles = ["window"]
        collector.driver = driver
        snapshot = [{"code": "Target123", "is_target": True}]
        snapshot.extend(
            {"code": f"Comment{index}", "comment": f"Komentar {index}"}
            for index in range(2_050)
        )
        progress = []

        with patch.object(collector, "_threads_dom_rows", return_value=snapshot):
            rows = collector._load_conversation(
                "Target123",
                max_comments=2_000,
                progress_callback=lambda count, limit: progress.append((count, limit)),
            )

        self.assertEqual(sum(bool(row.get("comment")) for row in rows), 2_000)
        self.assertEqual(progress[-1], (2_000, 2_000))
        driver.execute_script.assert_not_called()

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

    def test_threads_dom_rows_ignore_recommendations_when_target_is_missing(self):
        collector = CommentBrowserCollector("Threads")
        rows = [
            {
                "code": "Recommendation456",
                "author": "akun_lain",
                "comment": "Posting rekomendasi",
                "likes": "500",
                "replies": "12",
                "comment_type": "parent",
            }
        ]
        with patch.object(collector, "_threads_dom_rows", return_value=rows):
            comments = collector._dom_comments(
                "https://www.threads.com/@kokobuncis/post/DcQMIAFm_xq"
            )

        self.assertEqual(comments, [])

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

    def test_threads_collection_combines_initial_payload_with_scrolled_comments(self):
        collector = CommentBrowserCollector("Threads")
        driver = MagicMock()
        driver.window_handles = ["window"]
        driver.current_url = "https://www.threads.com/@pemilik/post/Target123"
        driver.page_source = "<html></html>"
        collector.driver = driver
        initial = PublicComment(
            author="ayu",
            comment="Komentar dari data awal",
            source_url=driver.current_url,
        )
        duplicate = PublicComment(
            author="ayu",
            comment="Komentar dari data awal",
            source_url=driver.current_url,
        )
        additional = PublicComment(
            author="bima",
            comment="Komentar yang muncul setelah scroll",
            comment_type="reply",
            source_url=driver.current_url,
        )
        collected_rows = [
            {"code": "Target123", "is_target": True},
            {"code": "Comment456", "author": "bima", "comment": additional.comment},
        ]
        connector = MagicMock()
        connector._platform_comments.return_value = [initial]

        with (
            patch("src.comment_browser.get_platform_connector", return_value=connector),
            patch.object(collector, "_wait_for_page"),
            patch.object(collector, "_load_conversation", return_value=collected_rows) as loader,
            patch.object(collector, "_dom_comments", return_value=[duplicate, additional]) as dom_comments,
        ):
            result = collector.collect(driver.current_url)

        loader.assert_called_once_with(
            "Target123",
            max_comments=2_000,
            progress_callback=None,
        )
        dom_comments.assert_called_once_with(driver.current_url, collected_rows)
        self.assertEqual(
            [comment.comment for comment in result.comments],
            ["Komentar dari data awal", "Komentar yang muncul setelah scroll"],
        )
        self.assertEqual(result.comments[1].comment_type, "reply")

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
