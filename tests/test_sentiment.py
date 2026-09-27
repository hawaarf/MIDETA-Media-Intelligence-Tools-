# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import unittest

from src.sentiment import classify_comment_tone


class CommentSentimentTests(unittest.TestCase):
    def test_negative_comment(self):
        self.assertEqual(classify_comment_tone("Pelayanannya buruk dan lambat 👎"), "Negative")

    def test_negated_positive_word_is_negative(self):
        self.assertEqual(classify_comment_tone("Ini tidak bagus dan kurang membantu"), "Negative")

    def test_positive_comment(self):
        self.assertEqual(classify_comment_tone("Bagus, sangat membantu. Terima kasih!"), "Positive")

    def test_tone_schema_remains_binary(self):
        self.assertEqual(classify_comment_tone("Informasi diterima"), "Positive")


if __name__ == "__main__":
    unittest.main()
