import unittest
from src.batch import SOCIAL_BATCH_VERSION, compact_social_export_row, is_current_social_batch, parse_url_list, rank_comment_rows, social_result_row
from src.connectors import get_connector

class BatchTests(unittest.TestCase):
    def test_parse_url_list_removes_blanks_and_duplicates(self):
        value = "https://youtube.com/watch?v=1\n\nhttps://x.com/a/status/2\nhttps://youtube.com/watch?v=1"
        self.assertEqual(parse_url_list(value), ["https://youtube.com/watch?v=1", "https://x.com/a/status/2"])

    def test_stale_social_batch_is_rejected_after_parser_update(self):
        self.assertFalse(is_current_social_batch({"results": []}))
        self.assertFalse(is_current_social_batch({"schema_version": SOCIAL_BATCH_VERSION - 1, "results": []}))
        self.assertTrue(is_current_social_batch({"schema_version": SOCIAL_BATCH_VERSION, "results": []}))

    def test_comment_ranking_uses_likes_and_replies(self):
        rows = [{"Komentar": "A", "Likes": 12, "Jumlah reply": 0}, {"Komentar": "B", "Likes": 8, "Jumlah reply": 4}, {"Komentar": "C", "Likes": None, "Jumlah reply": 1}]
        ranked = rank_comment_rows(rows)
        self.assertEqual([row["Komentar"] for row in ranked], ["B", "A", "C"])
        self.assertEqual([row["Rank"] for row in ranked], [1, 2, 3])

    def test_social_export_contains_requested_metrics(self):
        result = get_connector("https://youtu.be/demo").mock_enrichment("https://youtu.be/demo")
        row = social_result_row(result)
        for key in ("Tanggal posting", "Author", "Caption", "Followers", "Views", "Likes", "Comments", "Save atau bookmark", "Shares", "Reposts"):
            self.assertIn(key, row)

    def test_compact_social_export_has_no_blank_cells_or_repeated_status_columns(self):
        result = get_connector("https://youtu.be/demo").mock_enrichment("https://youtu.be/demo")
        result.caption.value = "Baris pertama\n\nBaris kedua"
        result.followers.value = None
        row = compact_social_export_row(result)
        self.assertNotIn("\n", row["Caption"])
        self.assertEqual(row["Followers"], "Tidak tersedia")
        self.assertIn("Followers", row["Data yang tidak tersedia"])
        self.assertFalse(any(column.startswith("Status ") for column in row))
        self.assertFalse(any(value in (None, "") for value in row.values()))
        self.assertEqual(len(row), 14)
