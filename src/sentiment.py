# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

"""Small deterministic sentiment helpers used by MIDETA exports."""
from __future__ import annotations

import re


_POSITIVE_PHRASES = (
    "bagus", "baik", "mantap", "keren", "hebat", "sukses", "setuju",
    "terima kasih", "makasih", "membantu", "bermanfaat", "suka", "cinta",
    "puas", "lancar", "cepat", "aman", "terbaik", "salut", "semangat",
    "good", "great", "awesome", "amazing", "love", "thanks", "helpful",
    "excellent", "nice", "well done",
)
_NEGATIVE_PHRASES = (
    "buruk", "jelek", "gagal", "bohong", "korup", "marah", "kecewa",
    "rugi", "masalah", "parah", "bodoh", "goblok", "tolol", "benci",
    "payah", "salah", "tipu", "penipuan", "hoaks", "hoax", "sampah",
    "kacau", "mahal", "lambat", "susah", "tidak setuju", "gak setuju",
    "ga setuju", "nggak setuju", "worst", "bad", "terrible", "scam",
    "hate", "disappointed", "angry", "fail", "corrupt", "fraud",
)
_POSITIVE_EMOJI = ("👍", "❤", "❤️", "😍", "🥰", "😊", "😁", "👏", "🔥", "🎉", "💯")
_NEGATIVE_EMOJI = ("👎", "😡", "🤬", "😠", "😞", "😢", "😭", "💔", "🤮", "🤢")


def _phrase_score(text: str, phrases: tuple[str, ...]) -> int:
    return sum(
        len(re.findall(rf"(?<!\w){re.escape(phrase)}(?!\w)", text))
        for phrase in phrases
    )


def classify_comment_tone(value) -> str:
    """Return the requested binary comment tone: ``Positive`` or ``Negative``.

    This lightweight classifier is intentionally deterministic so CSV results
    remain reproducible. Comments without a clear negative cue default to
    Positive instead of introducing a third label outside the requested schema.
    """
    text = " ".join(str(value or "").casefold().split())
    positive = _phrase_score(text, _POSITIVE_PHRASES)
    negative = _phrase_score(text, _NEGATIVE_PHRASES)
    negative += 2 * len(re.findall(
        r"(?<!\w)(?:tidak|tak|gak|ga|nggak|kurang|not|never)\s+"
        r"(?:bagus|baik|mantap|membantu|bermanfaat|puas|aman|good|great|helpful|nice)(?!\w)",
        text,
    ))
    positive += sum(text.count(emoji) for emoji in _POSITIVE_EMOJI)
    negative += sum(text.count(emoji) for emoji in _NEGATIVE_EMOJI)
    return "Negative" if negative > positive else "Positive"
