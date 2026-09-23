# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import unittest
import json
from unittest.mock import MagicMock, patch

from selenium.common.exceptions import NoSuchWindowException

from src.comment_browser import CommentBrowserCollector
from src.models import FieldStatus, PublicComment


class CommentBrowserTests(unittest.TestCase):
    def test_threads_enrichment_uses_exact_post_and_profile_page(self):
        collector = CommentBrowserCollector("Threads")
        url = "https://www.threads.com/@ojoldiary/post/DdaVM2LE1aI"
        post_html = """<html><body><header>2.2K views</header><script type="application/json">
        {"media":{"code":"DdaVM2LE1aI","taken_at":1789697514,
        "user":{"username":"ojoldiary"},"caption":{"text":"Caption target"},
        "like_count":15,"text_post_app_info":{"direct_reply_count":9,
        "repost_count":3,"reshare_count":4}}}</script></body></html>"""
        profile_html = """<html><meta property="og:description"
        content="508 Followers • 33 Threads"></html>"""
        driver = MagicMock()
        driver.window_handles = ["window"]
        driver.current_window_handle = "window"
        driver.current_url = url
        driver.page_source = post_html
        driver.execute_script.return_value = "2.2K views"

        def navigate(target):
            driver.current_url = target
            driver.page_source = profile_html if target.endswith("/@ojoldiary") else post_html

        driver.get.side_effect = navigate
        collector.driver = driver

        with patch.object(collector, "_wait_for_page"):
            result = collector.collect_threads_enrichment(url)

        self.assertEqual(driver.get.call_args_list[0].args[0], url)
        self.assertEqual(driver.get.call_args_list[1].args[0], "https://www.threads.com/@ojoldiary")
        self.assertEqual(result.caption.value, "Caption target")
        self.assertEqual(result.followers.value, 508)
        self.assertEqual(result.views.value, 2_200)
        self.assertEqual(result.comments.value, 9)

    def test_threads_visible_views_ignores_unlabeled_numbers(self):
        driver = MagicMock()
        driver.execute_script.return_value = "15 9 3 4"

        self.assertIsNone(CommentBrowserCollector._threads_visible_views(driver))

    def test_threads_visible_views_accepts_indonesian_labels(self):
        driver = MagicMock()
        driver.execute_script.side_effect = ["2,2 rb kali dilihat", "Dilihat: 2,2 rb"]

        self.assertEqual(CommentBrowserCollector._threads_visible_views(driver), 2_200)
        self.assertEqual(CommentBrowserCollector._threads_visible_views(driver), 2_200)

    def test_threads_detail_url_opens_thread_header_route(self):
        self.assertEqual(
            CommentBrowserCollector._threads_detail_url(
                "https://www.threads.com/@ojoldiary/post/DdaVM2LE1aI/"
            ),
            "https://www.threads.com/@ojoldiary/post/DdaVM2LE1aI#/",
        )
        self.assertEqual(
            CommentBrowserCollector._threads_detail_url(
                "https://www.threads.com/share/RrTdJihUN/"
            ),
            "https://www.threads.com/share/RrTdJihUN/",
        )

    def test_threads_target_card_click_uses_exact_shortcode(self):
        driver = MagicMock()
        driver.execute_script.return_value = True

        self.assertTrue(
            CommentBrowserCollector._open_threads_target_card(driver, "DdaVM2LE1aI")
        )
        self.assertEqual(driver.execute_script.call_args.args[1], "DdaVM2LE1aI")

    def test_dead_browser_window_is_reopened_automatically(self):
        collector = CommentBrowserCollector("Threads")
        stale_driver = MagicMock()
        collector.driver = stale_driver
        recovered = MagicMock()

        with patch.object(
            collector,
            "_collect_once",
            side_effect=[NoSuchWindowException("target window already closed"), recovered],
        ) as collect_once:
            result = collector.collect("https://www.threads.com/@akun/post/Target123")

        self.assertIs(result, recovered)
        self.assertEqual(collect_once.call_count, 2)
        stale_driver.quit.assert_called_once_with()

    def test_threads_share_url_uses_permalink_exposed_by_the_page(self):
        collector = CommentBrowserCollector("Threads")
        short_url = "https://www.threads.com/share/RrTdJihUN/"
        permalink = "https://www.threads.com/@akun/post/Target123"
        driver = MagicMock()
        driver.window_handles = ["window"]
        driver.current_window_handle = "window"
        driver.current_url = short_url
        driver.page_source = "<html></html>"
        driver.execute_script.return_value = [short_url, permalink, "", ""]
        driver.get.side_effect = lambda target: setattr(
            driver,
            "current_url",
            permalink if "/@akun/post/Target123" in target else short_url,
        )
        collector.driver = driver
        connector = MagicMock()
        connector._platform_comments.return_value = []
        visible = PublicComment(author="ayu", comment="Komentar Threads", source_url=permalink)

        with (
            patch("src.comment_browser.get_platform_connector", return_value=connector),
            patch.object(collector, "_wait_for_page"),
            patch.object(collector, "_activate_threads_target", return_value=permalink) as activate,
            patch.object(collector, "_load_conversation", return_value=[{"code": "Target123"}]) as loader,
            patch.object(collector, "_dom_comments", return_value=[visible]) as dom_comments,
        ):
            result = collector.collect(short_url)

        activate.assert_called_once_with(driver, permalink, "Target123")
        loader.assert_called_once_with(
            "Target123",
            max_comments=2_000,
            progress_callback=None,
        )
        dom_comments.assert_called_once_with(permalink, [{"code": "Target123"}])
        self.assertEqual(result.url, permalink)
        self.assertEqual(result.comments[0].comment, "Komentar Threads")

    def test_threads_share_url_does_not_use_a_recommended_post_link(self):
        short_url = "https://www.threads.com/share/RrTdJihUN/"
        recommendation = "https://www.threads.com/@lain/post/Recommendation123"
        driver = MagicMock()
        driver.current_url = short_url
        # The fourth value represents the old generic first-post fallback.
        # It must never be accepted as the share target.
        driver.execute_script.return_value = [short_url, "", "", recommendation]

        self.assertEqual(
            CommentBrowserCollector._threads_permalink(driver, short_url),
            short_url,
        )

    def test_threads_home_injected_card_is_opened_by_exact_shortcode(self):
        collector = CommentBrowserCollector("Threads")
        target = "https://www.threads.com/@pemilik/post/Target123"
        driver = MagicMock()
        driver.current_url = "https://www.threads.com/"

        def open_target(_driver, code):
            self.assertEqual(code, "Target123")
            driver.current_url = target
            return True

        with patch.object(collector, "_open_threads_target_card", side_effect=open_target):
            active = collector._activate_threads_target(
                driver,
                "https://www.threads.com/@nama-lama/post/Target123",
                "Target123",
            )

        self.assertEqual(active, target)
        driver.get.assert_not_called()

    def test_threads_loader_only_opens_replies_inside_target_conversation(self):
        collector = CommentBrowserCollector("Threads")
        collector.THREADS_MAX_SCROLL_ROUNDS = 1
        driver = MagicMock()
        driver.window_handles = ["window"]
        driver.execute_script.return_value = {
            "reachedEnd": True,
            "clicked": 1,
            "scrollY": 100,
            "height": 1_000,
            "targetLocked": True,
        }
        collector.driver = driver
        rows = [
            {"code": "Target123", "is_target": True},
            {"code": "Comment456", "comment": "Komentar", "comment_type": "parent"},
            {"code": "Reply789", "comment": "Balasan", "comment_type": "reply"},
        ]

        with (
            patch.object(collector, "_threads_dom_rows", return_value=rows),
            patch("src.comment_browser.time.sleep"),
        ):
            result = collector._load_conversation("Target123")

        script_call = driver.execute_script.call_args
        self.assertEqual(script_call.args[2], "Target123")
        self.assertIn("insideTargetConversation", script_call.args[0])
        self.assertIn("leafLoaders", script_call.args[0])
        self.assertNotIn("targetAnchor ||", script_call.args[0])
        self.assertEqual(
            [row["comment_type"] for row in result if row.get("comment")],
            ["parent", "reply"],
        )

    def test_threads_comment_metrics_read_button_text_content(self):
        collector = CommentBrowserCollector("Threads")
        driver = MagicMock()
        driver.window_handles = ["window"]
        driver.execute_script.return_value = []
        collector.driver = driver

        collector._threads_dom_rows("Target123")

        script = driver.execute_script.call_args.args[0]
        self.assertIn("button, [role=\"button\"]", script)
        self.assertIn("node.textContent", script)
        self.assertIn("control.textContent", script)
        self.assertEqual(collector._count("Like1 Like"), 1)

    def test_threads_loader_restores_target_if_the_page_changes_post(self):
        collector = CommentBrowserCollector("Threads")
        collector.THREADS_MAX_SCROLL_ROUNDS = 1
        target = "https://www.threads.com/@pemilik/post/Target123"
        driver = MagicMock()
        driver.window_handles = ["window"]
        driver.current_url = target
        driver.execute_script.return_value = {
            "reachedEnd": True,
            "clicked": 0,
            "scrollY": 100,
            "height": 1_000,
            "targetLocked": False,
        }
        collector.driver = driver

        with (
            patch.object(
                collector,
                "_threads_dom_rows",
                return_value=[{"code": "Target123", "is_target": True}],
            ),
            patch.object(collector, "_wait_for_page"),
            patch("src.comment_browser.time.sleep"),
        ):
            collector._load_conversation("Target123")

        driver.get.assert_called_once_with(f"{target}#/")

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

    def test_facebook_advanced_reads_followers_and_exact_reel_views(self):
        collector = CommentBrowserCollector("Facebook")
        url = "https://www.facebook.com/reel/123"
        profile_url = "https://www.facebook.com/echy"
        post_html = (
            '<html><head><meta property="og:url" content="https://www.facebook.com/reel/123">'
            '<meta property="og:description" content="Caption target"></head>'
            '<script>{"feedback":{"subscription_target_id":"123",'
            '"reaction_count":{"count":38},"total_comment_count":12},'
            '"video_owner":{"name":"Echy","url":"https:\\/\\/www.facebook.com\\/echy"}}</script></html>'
        )
        profile_html = "<html><body><strong>7.5K followers</strong></body></html>"
        reels_html = (
            '<html><a href="/reel/999"><span>9.9K</span></a>'
            '<a href="/reel/123"><span aria-label="812 views">812</span></a></html>'
        )
        driver = MagicMock()
        driver.window_handles = ["window"]
        driver.current_window_handle = "window"
        driver.current_url = url
        driver.page_source = post_html
        driver.get_cookies.return_value = [{"name": "c_user", "value": "1000123456789"}]

        def navigate(target):
            driver.current_url = target
            if target == profile_url:
                driver.page_source = profile_html
            elif target == f"{profile_url}/reels/":
                driver.page_source = reels_html
            else:
                driver.page_source = post_html

        driver.get.side_effect = navigate
        driver.execute_script.return_value = [url, url, url]
        collector.driver = driver

        with patch.object(collector, "_wait_for_page"):
            result = collector.collect_facebook_enrichment(url)

        self.assertEqual(result.username.value, "Echy")
        self.assertEqual(result.caption.value, "Caption target")
        self.assertEqual(result.followers.value, 7_500)
        self.assertEqual(result.views.value, 812)
        self.assertEqual(result.likes.value, 38)
        self.assertEqual(result.comments.value, 12)
        self.assertIn(f"{profile_url}/reels/", [call.args[0] for call in driver.get.call_args_list])

    def test_facebook_share_waits_for_resolved_post_permalink(self):
        short_url = "https://www.facebook.com/share/p/Example/"
        permalink = "https://www.facebook.com/maskurcokern7/posts/pfbidTarget"
        driver = MagicMock()
        driver.current_url = permalink
        driver.execute_script.return_value = [short_url, "", ""]

        self.assertEqual(
            CommentBrowserCollector._facebook_permalink(driver, short_url),
            permalink,
        )

    def test_facebook_target_match_rejects_a_stale_previous_reel(self):
        expected = "https://www.facebook.com/reel/123"

        self.assertTrue(
            CommentBrowserCollector._same_facebook_target(
                expected,
                "https://www.facebook.com/reel/123?tracking=abc",
            )
        )
        self.assertFalse(
            CommentBrowserCollector._same_facebook_target(
                expected,
                "https://www.facebook.com/reel/999",
            )
        )

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

    def test_facebook_reel_opener_supports_komentari_control(self):
        collector = CommentBrowserCollector("Facebook")
        driver = MagicMock()
        driver.window_handles = ["window"]
        driver.execute_script.side_effect = [True, False]
        collector.driver = driver

        with patch("src.comment_browser.time.sleep"):
            collector._prepare_facebook_comments()

        opener_script = driver.execute_script.call_args_list[0].args[0]
        self.assertIn("komentari", opener_script.casefold())
        self.assertIn("aria-label", opener_script)

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

    def test_threads_loader_stops_after_comments_stop_changing(self):
        collector = CommentBrowserCollector("Threads")
        collector.THREADS_MAX_SCROLL_ROUNDS = 50
        driver = MagicMock()
        driver.window_handles = ["window"]
        driver.current_window_handle = "window"
        driver.execute_script.side_effect = [
            {"reachedEnd": False, "clicked": 0, "scrollY": index * 100, "height": 20_000}
            for index in range(1, 51)
        ]
        collector.driver = driver
        snapshot = [
            {"code": "Target123", "is_target": True},
            {"code": "Comment1", "author": "ayu", "comment": "Komentar pertama"},
        ]

        with (
            patch.object(collector, "_threads_dom_rows", return_value=snapshot),
            patch("src.comment_browser.time.sleep"),
        ):
            rows = collector._load_conversation("Target123")

        self.assertEqual([row["code"] for row in rows], ["Target123", "Comment1"])
        # The first round stores the initial comments, then twelve unchanged
        # rounds confirm that the visible conversation is exhausted.
        self.assertEqual(driver.execute_script.call_count, 13)

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

    def test_x_switches_relevant_filter_to_latest_replies(self):
        collector = CommentBrowserCollector("X")
        driver = MagicMock()
        driver.window_handles = ["window"]
        driver.current_window_handle = "window"
        driver.execute_script.side_effect = [True, True]
        collector.driver = driver

        with patch("src.comment_browser.time.sleep"):
            collector._prepare_x_comments()

        self.assertEqual(driver.execute_script.call_count, 2)
        self.assertIn("relevant", driver.execute_script.call_args_list[0].args[0])
        self.assertIn("latest", driver.execute_script.call_args_list[1].args[0])
        self.assertIn("terbaru", driver.execute_script.call_args_list[1].args[0])

    def test_x_loader_waits_for_delayed_replies_when_total_is_known(self):
        collector = CommentBrowserCollector("X")
        collector.X_MAX_SCROLL_ROUNDS = 10
        driver = MagicMock()
        driver.window_handles = ["window"]
        driver.current_window_handle = "window"
        driver.execute_script.return_value = {
            "reachedEnd": False,
            "clicked": 0,
            "scrollY": 100,
            "height": 1_000,
            "targetLocked": True,
        }
        collector.driver = driver
        dom_reads = 0

        def delayed_rows():
            nonlocal dom_reads
            dom_reads += 1
            if dom_reads >= 17:
                return [{"code": "101", "comment": "Balasan terlambat"}]
            return []

        with (
            patch.object(collector, "_x_dom_rows", side_effect=delayed_rows),
            patch("src.comment_browser.time.sleep"),
        ):
            rows = collector._load_conversation(
                "100",
                max_comments=2_000,
                expected_comments=1,
            )

        self.assertEqual([row["comment"] for row in rows], ["Balasan terlambat"])
        self.assertEqual(driver.execute_script.call_count, 8)

    def test_x_dom_reader_scopes_end_markers_to_primary_column(self):
        collector = CommentBrowserCollector("X")
        driver = MagicMock()
        driver.window_handles = ["window"]
        driver.current_window_handle = "window"
        driver.execute_script.return_value = []
        collector.driver = driver

        collector._x_dom_rows()

        script = driver.execute_script.call_args.args[0]
        self.assertIn('data-testid="primaryColumn"', script)
        self.assertIn("conversation.querySelectorAll", script)

    def test_x_captured_payload_keeps_all_replies_from_target_conversation(self):
        payload = {
            "data": {
                "threaded_conversation_with_injections_v2": {
                    "instructions": [
                        {
                            "entries": [
                                {
                                    "content": {
                                        "itemContent": {
                                            "tweet_results": {
                                                "result": {
                                                    "rest_id": "100",
                                                    "legacy": {
                                                        "conversation_id_str": "100",
                                                        "full_text": "Posting target",
                                                    },
                                                }
                                            }
                                        }
                                    }
                                },
                                {
                                    "content": {
                                        "itemContent": {
                                            "tweet_results": {
                                                "result": {
                                                    "rest_id": "101",
                                                    "core": {
                                                        "user_results": {
                                                            "result": {
                                                                "core": {"screen_name": "ayu"}
                                                            }
                                                        }
                                                    },
                                                    "legacy": {
                                                        "conversation_id_str": "100",
                                                        "in_reply_to_status_id_str": "100",
                                                        "in_reply_to_screen_name": "pemilik",
                                                        "full_text": "Balasan langsung",
                                                        "favorite_count": 12,
                                                        "reply_count": 1,
                                                    },
                                                }
                                            }
                                        }
                                    }
                                },
                                {
                                    "content": {
                                        "itemContent": {
                                            "tweet_results": {
                                                "result": {
                                                    "rest_id": "102",
                                                    "core": {
                                                        "user_results": {
                                                            "result": {
                                                                "legacy": {"screen_name": "bima"}
                                                            }
                                                        }
                                                    },
                                                    "legacy": {
                                                        "conversation_id_str": "100",
                                                        "in_reply_to_status_id_str": "101",
                                                        "full_text": "Balasan bertingkat",
                                                        "favorite_count": 3,
                                                    },
                                                }
                                            }
                                        }
                                    }
                                },
                                {
                                    "content": {
                                        "itemContent": {
                                            "tweet_results": {
                                                "result": {
                                                    "rest_id": "999",
                                                    "legacy": {
                                                        "conversation_id_str": "999",
                                                        "in_reply_to_status_id_str": "999",
                                                        "full_text": "Posting rekomendasi",
                                                    },
                                                }
                                            }
                                        }
                                    }
                                },
                            ]
                        }
                    ]
                }
            }
        }

        rows = CommentBrowserCollector._x_payload_rows(
            [{"url": "https://x.com/i/api/graphql/query/TweetDetail", "body": json.dumps(payload)}],
            "100",
        )

        self.assertEqual([row["code"] for row in rows], ["100", "101", "102"])
        self.assertEqual([row["comment_type"] for row in rows[1:]], ["parent", "reply"])
        self.assertEqual(rows[1]["likes"], 12)
        self.assertEqual(rows[2]["author"], "bima")

    def test_x_response_capture_is_installed_before_opening_post(self):
        collector = CommentBrowserCollector("X")
        url = "https://x.com/pemilik/status/100"
        driver = MagicMock()
        driver.window_handles = ["window"]
        driver.current_window_handle = "window"
        driver.current_url = url
        driver.page_source = "<html></html>"
        collector.driver = driver
        connector = MagicMock()
        connector._platform_comments.return_value = []
        events = []
        driver.execute_cdp_cmd.side_effect = lambda *args, **kwargs: events.append("capture")
        driver.get.side_effect = lambda *args, **kwargs: events.append("get")

        with (
            patch("src.comment_browser.get_platform_connector", return_value=connector),
            patch.object(collector, "_wait_for_page"),
            patch.object(collector, "_prepare_x_comments"),
            patch.object(collector, "_load_conversation", return_value=[]),
            patch.object(collector, "is_logged_in", return_value=True),
        ):
            collector.collect(url)

        self.assertEqual(events[:2], ["capture", "get"])

    def test_x_collection_uses_expected_total_and_reports_incomplete_visibility(self):
        collector = CommentBrowserCollector("X")
        url = "https://x.com/tempodotco/status/2100857368166711315"
        driver = MagicMock()
        driver.window_handles = ["window"]
        driver.current_window_handle = "window"
        driver.current_url = url
        driver.page_source = "<html></html>"
        collector.driver = driver
        connector = MagicMock()
        connector._platform_comments.return_value = []
        visible = PublicComment(author="ayu", comment="Balasan terlihat", source_url=url)

        with (
            patch("src.comment_browser.get_platform_connector", return_value=connector),
            patch.object(collector, "_wait_for_page"),
            patch.object(collector, "_prepare_x_comments") as prepare,
            patch.object(collector, "_load_conversation", return_value=[{"code": "101"}]) as loader,
            patch.object(collector, "_dom_comments", return_value=[visible]),
        ):
            result = collector.collect(url, expected_comments=46)

        prepare.assert_called_once_with()
        loader.assert_called_once_with(
            "2100857368166711315",
            max_comments=2_000,
            expected_comments=46,
            progress_callback=None,
        )
        self.assertEqual(len(result.comments), 1)
        self.assertIn("1 dari sekitar 46 balasan", result.reason)

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

    def test_facebook_open_login_goes_directly_to_login_without_waiting_for_home(self):
        collector = CommentBrowserCollector("Facebook")
        driver = MagicMock()
        driver.window_handles = ["window"]
        collector.driver = driver

        with (
            patch.object(collector, "_wait_for_page") as page_wait,
            patch.object(collector, "is_logged_in", return_value=True) as login_check,
        ):
            session_active = collector.open_login()

        self.assertTrue(session_active)
        driver.get.assert_called_once_with("https://www.facebook.com/login/")
        page_wait.assert_not_called()
        login_check.assert_called_once_with(open_platform=False)


if __name__ == "__main__":
    unittest.main()
