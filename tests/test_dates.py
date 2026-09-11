import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from src.dates import parse_relative_social_datetime, relative_social_date_iso


class SocialDateTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 11, 10, 30, tzinfo=ZoneInfo("Asia/Jakarta"))

    def test_instagram_day_label_subtracts_exact_calendar_days(self):
        self.assertEqual(relative_social_date_iso("2d ago", now=self.now), "2026-09-09")

    def test_facebook_hour_label_stays_on_the_same_day(self):
        parsed = parse_relative_social_datetime("2 hr", now=self.now)
        self.assertEqual(parsed.isoformat(), "2026-09-11T08:30:00+07:00")

    def test_hour_label_can_cross_midnight(self):
        early = datetime(2026, 9, 11, 1, 0, tzinfo=ZoneInfo("Asia/Jakarta"))
        self.assertEqual(relative_social_date_iso("3 hours ago", now=early), "2026-09-10")

    def test_indonesian_relative_labels(self):
        self.assertEqual(relative_social_date_iso("2 hari lalu", now=self.now), "2026-09-09")
        self.assertEqual(relative_social_date_iso("kemarin", now=self.now), "2026-09-10")


if __name__ == "__main__":
    unittest.main()
