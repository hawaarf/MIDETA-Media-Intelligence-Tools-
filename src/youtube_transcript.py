# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

"""Single-video YouTube transcript collection and speaker-label parsing."""
from __future__ import annotations

from dataclasses import dataclass
import html
import json
import re
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urlparse

import requests

from src.config import MAX_RESPONSE_BYTES, REQUEST_TIMEOUT_SECONDS
from src.http_client import USER_AGENT
from src.social_urls import canonical_social_url, platform_from_url


_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
_TIMING_RE = re.compile(
    r"^(?P<start>(?:\d{1,2}:)?\d{2}:\d{2}[.,]\d{3})\s*-->\s*"
    r"(?P<end>(?:\d{1,2}:)?\d{2}:\d{2}[.,]\d{3})"
)
_VOICE_RE = re.compile(r"<v(?:\.[^ >]+)*\s+([^>]+)>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_PREFIX_SPEAKER_RE = re.compile(
    r"^\s*(?:>>\s*)?(?:\[([^\]]{1,60})\]|([^:\n]{1,60}))\s*:\s*(.+)$",
    re.S,
)
_NON_SPEECH_RE = re.compile(
    r"^\s*[\[(](?:music|musik|applause|tepuk tangan|laughter|tertawa|silence|hening|"
    r"foreign|inaudible|tidak terdengar)[\])]\s*$",
    re.I,
)
_GENERIC_SPEAKER_RE = re.compile(r"^(?:Pembicara|Speaker)\s+\d+$", re.I)


class YouTubeTranscriptError(RuntimeError):
    """Raised when a public YouTube transcript cannot be collected."""


@dataclass(slots=True)
class TranscriptSegment:
    start_seconds: float
    text: str
    speaker: str
    speaker_from_caption: bool = False


@dataclass(slots=True)
class YouTubeTranscriptResult:
    source_url: str
    title: str
    channel: str
    language_code: str
    language_name: str
    caption_source: str
    segments: list[TranscriptSegment]
    spokespersons: tuple[str, ...]
    has_named_speakers: bool


@dataclass(slots=True)
class _SpeakerState:
    current: str = ""
    generic_count: int = 0

    def generic(self, *, next_speaker: bool = False) -> str:
        if not self.current or next_speaker or not _GENERIC_SPEAKER_RE.fullmatch(self.current):
            self.generic_count += 1
            self.current = f"Pembicara {self.generic_count}"
        return self.current


class _QuietLogger:
    def debug(self, _message: str) -> None:
        pass

    def warning(self, _message: str) -> None:
        pass

    def error(self, _message: str) -> None:
        pass


def _video_url(value: str) -> str:
    raw = str(value or "").strip()
    if platform_from_url(raw) != "YouTube":
        raise YouTubeTranscriptError("Masukkan satu URL video YouTube yang valid.")
    canonical = canonical_social_url(raw, "YouTube") or ""
    parsed = urlparse(canonical)
    video_id = (parse_qs(parsed.query).get("v") or [""])[0]
    if not _VIDEO_ID_RE.fullmatch(video_id):
        raise YouTubeTranscriptError(
            "URL harus mengarah ke satu video, Shorts, atau live replay YouTube."
        )
    return canonical


def format_timestamp(seconds: float) -> str:
    total = max(0, int(float(seconds or 0)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _timestamp_seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    raise ValueError("Invalid caption timestamp")


def _clean_caption_text(value: str) -> str:
    text = html.unescape(str(value or ""))
    text = _TAG_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    if _NON_SPEECH_RE.fullmatch(text):
        return ""
    return text


def _valid_speaker_name(value: str) -> bool:
    name = re.sub(r"\s+", " ", html.unescape(value)).strip(" -–—[]()")
    if not name or len(name) > 60 or len(name.split()) > 7:
        return False
    if _NON_SPEECH_RE.fullmatch(f"[{name}]"):
        return False
    if re.search(r"https?://|www\.|[@#]", name, re.I):
        return False
    return bool(re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", name)) and not bool(
        re.search(r"[.!?]$", name)
    )


def _speaker_and_text(raw_text: str, state: _SpeakerState) -> tuple[str, str, bool]:
    source = html.unescape(str(raw_text or "")).strip()
    voice_match = _VOICE_RE.search(source)
    if voice_match and _valid_speaker_name(voice_match.group(1)):
        state.current = re.sub(r"\s+", " ", voice_match.group(1)).strip()
        text = _clean_caption_text(source)
        return state.current, text, True

    changed_without_name = source.startswith(">>")
    prefix_match = _PREFIX_SPEAKER_RE.match(source)
    if prefix_match:
        candidate = prefix_match.group(1) or prefix_match.group(2) or ""
        if _valid_speaker_name(candidate):
            state.current = re.sub(r"\s+", " ", candidate).strip()
            return state.current, _clean_caption_text(prefix_match.group(3)), True

    source = re.sub(r"^>>\s*", "", source)
    if changed_without_name:
        speaker = state.generic(next_speaker=True)
    elif state.current:
        speaker = state.current
    else:
        speaker = state.generic()
    return speaker, _clean_caption_text(source), False


def _deduplicate_rolling(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    output: list[TranscriptSegment] = []
    for segment in segments:
        if not segment.text:
            continue
        if output:
            previous = output[-1]
            same_speaker = previous.speaker == segment.speaker
            close_in_time = segment.start_seconds - previous.start_seconds <= 8
            previous_folded = previous.text.casefold()
            current_folded = segment.text.casefold()
            if same_speaker and current_folded == previous_folded:
                continue
            if same_speaker and close_in_time and current_folded.startswith(previous_folded + " "):
                previous.text = segment.text
                previous.speaker_from_caption = (
                    previous.speaker_from_caption or segment.speaker_from_caption
                )
                continue
            if same_speaker and close_in_time and previous_folded.startswith(current_folded + " "):
                continue
        output.append(segment)
    return output


def parse_vtt(payload: str) -> list[TranscriptSegment]:
    """Parse WebVTT captions, including voice tags and ``Speaker:`` prefixes."""
    lines = str(payload or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    segments: list[TranscriptSegment] = []
    state = _SpeakerState()
    index = 0
    while index < len(lines):
        match = _TIMING_RE.match(lines[index].strip())
        if not match:
            index += 1
            continue
        start = _timestamp_seconds(match.group("start"))
        index += 1
        cue_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            cue_lines.append(lines[index].strip())
            index += 1
        raw_text = " ".join(cue_lines)
        speaker, text, explicit = _speaker_and_text(raw_text, state)
        if text:
            segments.append(TranscriptSegment(start, text, speaker, explicit))
    return _deduplicate_rolling(segments)


def parse_json3(payload: str | Mapping[str, Any]) -> list[TranscriptSegment]:
    """Parse YouTube's JSON3 caption representation."""
    try:
        data = json.loads(payload) if isinstance(payload, str) else dict(payload)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise YouTubeTranscriptError("Format subtitle YouTube tidak dapat dibaca.") from exc

    segments: list[TranscriptSegment] = []
    state = _SpeakerState()
    for event in data.get("events") or []:
        if not isinstance(event, dict) or event.get("tStartMs") is None:
            continue
        parts = event.get("segs") or []
        raw_text = "".join(
            str(part.get("utf8") or "") for part in parts if isinstance(part, dict)
        )
        explicit_name = next(
            (
                str(value).strip()
                for value in (
                    event.get("speaker"),
                    event.get("speakerName"),
                    event.get("voice"),
                )
                if value and _valid_speaker_name(str(value))
            ),
            "",
        )
        if explicit_name:
            raw_text = f"{explicit_name}: {raw_text}"
        speaker, text, explicit = _speaker_and_text(raw_text, state)
        if not text:
            continue
        try:
            start = float(event.get("tStartMs") or 0) / 1000
        except (TypeError, ValueError):
            continue
        segments.append(TranscriptSegment(start, text, speaker, explicit))
    return _deduplicate_rolling(segments)


def parse_caption_payload(payload: str, extension: str = "") -> list[TranscriptSegment]:
    stripped = str(payload or "").lstrip("\ufeff \t\r\n")
    if extension.casefold() == "json3" or stripped.startswith("{"):
        return parse_json3(stripped)
    return parse_vtt(stripped)


def _language_keys(tracks: Mapping[str, Any], requested: str) -> list[str]:
    keys = [str(key) for key in tracks if str(key).casefold() != "live_chat"]
    if requested != "auto":
        folded = requested.casefold()
        return [key for key in keys if key.casefold() == folded or key.casefold().startswith(f"{folded}-")]
    preferred: list[str] = []
    for code in ("id", "en"):
        preferred.extend(
            key for key in keys
            if (key.casefold() == code or key.casefold().startswith(f"{code}-"))
            and key not in preferred
        )
    preferred.extend(key for key in keys if key not in preferred)
    return preferred


def _track_format(formats: Any) -> dict[str, Any] | None:
    if not isinstance(formats, list):
        return None
    for extension in ("vtt", "json3"):
        for item in formats:
            if (
                isinstance(item, dict)
                and str(item.get("ext") or "").casefold() == extension
                and str(item.get("url") or "").strip()
            ):
                return item
    return None


def _select_track(info: Mapping[str, Any], requested: str) -> tuple[str, str, str, dict[str, Any]]:
    sources = (
        ("manual", info.get("subtitles") or {}),
        ("automatic", info.get("automatic_captions") or {}),
    )
    for source_name, tracks in sources:
        if not isinstance(tracks, Mapping):
            continue
        for language_code in _language_keys(tracks, requested):
            selected = _track_format(tracks.get(language_code))
            if selected:
                language_name = str(selected.get("name") or language_code).strip()
                return source_name, language_code, language_name, selected

    if requested != "auto":
        language_label = "Indonesia" if requested == "id" else "English"
        raise YouTubeTranscriptError(
            f"Video ini tidak menyediakan subtitle {language_label}. Coba pilihan Otomatis."
        )
    raise YouTubeTranscriptError(
        "Video ini tidak menyediakan subtitle manual maupun subtitle otomatis YouTube."
    )


class YouTubeTranscriptCollector:
    """Collect one public YouTube transcript without downloading the video."""

    def __init__(
        self,
        *,
        request_timeout: int = REQUEST_TIMEOUT_SECONDS,
        info_provider: Callable[[str], Mapping[str, Any]] | None = None,
        subtitle_fetcher: Callable[[str, Mapping[str, str]], str] | None = None,
    ):
        self.request_timeout = request_timeout
        self.info_provider = info_provider
        self.subtitle_fetcher = subtitle_fetcher

    def _extract_info(self, url: str) -> Mapping[str, Any]:
        if self.info_provider is not None:
            return self.info_provider(url)
        try:
            import yt_dlp
            from yt_dlp.utils import DownloadError
        except ImportError as exc:
            raise YouTubeTranscriptError(
                "Dependency transcript belum terpasang. Jalankan pip install -r requirements.txt."
            ) from exc

        options = {
            "skip_download": True,
            "noplaylist": True,
            "socket_timeout": self.request_timeout,
            "quiet": True,
            "no_warnings": True,
            "logger": _QuietLogger(),
        }
        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(url, download=False)
        except DownloadError as exc:
            message = str(exc).casefold()
            if "private" in message:
                detail = "Video bersifat privat dan transcript publik tidak dapat dibaca."
            elif "unavailable" in message or "not available" in message:
                detail = "Video YouTube tidak tersedia atau dibatasi untuk wilayah/akun ini."
            elif "sign in" in message or "cookies" in message:
                detail = "YouTube meminta login untuk membuka video ini."
            else:
                detail = "YouTube belum dapat memproses video ini. Coba lagi beberapa saat."
            raise YouTubeTranscriptError(detail) from exc
        return info if isinstance(info, Mapping) else {}

    def _fetch_subtitle(self, url: str, headers: Mapping[str, str]) -> str:
        if self.subtitle_fetcher is not None:
            return self.subtitle_fetcher(url, headers)
        request_headers = {"User-Agent": USER_AGENT, **dict(headers)}
        try:
            with requests.get(
                url,
                headers=request_headers,
                timeout=self.request_timeout,
                stream=True,
            ) as response:
                response.raise_for_status()
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_content(64 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_RESPONSE_BYTES:
                        raise YouTubeTranscriptError("File subtitle YouTube terlalu besar untuk diproses.")
                    chunks.append(chunk)
                encoding = response.encoding or "utf-8"
                return b"".join(chunks).decode(encoding, errors="replace")
        except YouTubeTranscriptError:
            raise
        except requests.RequestException as exc:
            raise YouTubeTranscriptError(
                "File subtitle YouTube gagal diunduh. Coba proses ulang URL tersebut."
            ) from exc

    def collect(self, url: str, *, language: str = "auto") -> YouTubeTranscriptResult:
        source_url = _video_url(url)
        language_choice = str(language or "auto").casefold()
        if language_choice not in {"auto", "id", "en"}:
            raise YouTubeTranscriptError("Pilihan bahasa subtitle tidak dikenali.")

        info = self._extract_info(source_url)
        source_name, language_code, language_name, track = _select_track(
            info, language_choice
        )
        headers = info.get("http_headers") if isinstance(info.get("http_headers"), Mapping) else {}
        payload = self._fetch_subtitle(str(track.get("url") or ""), headers)
        segments = parse_caption_payload(payload, str(track.get("ext") or ""))
        if not segments:
            raise YouTubeTranscriptError(
                "Subtitle tersedia, tetapi tidak berisi kalimat yang dapat ditranskripsikan."
            )

        spokespersons = tuple(dict.fromkeys(segment.speaker for segment in segments))
        has_named_speakers = any(segment.speaker_from_caption for segment in segments)
        return YouTubeTranscriptResult(
            source_url=source_url,
            title=str(info.get("title") or "Video YouTube").strip(),
            channel=str(
                info.get("channel")
                or info.get("uploader")
                or info.get("creator")
                or "Tidak tersedia"
            ).strip(),
            language_code=language_code,
            language_name=language_name,
            caption_source=source_name,
            segments=segments,
            spokespersons=spokespersons,
            has_named_speakers=has_named_speakers,
        )


def _speaker_mapping(
    result: YouTubeTranscriptResult,
    speaker_names: Mapping[str, str] | None,
) -> dict[str, str]:
    names = speaker_names or {}
    return {
        speaker: re.sub(r"\s+", " ", str(names.get(speaker) or speaker)).strip()
        for speaker in result.spokespersons
    }


def format_transcript(
    result: YouTubeTranscriptResult,
    speaker_names: Mapping[str, str] | None = None,
) -> str:
    """Return the copy-ready transcript requested by reporting users."""
    names = _speaker_mapping(result, speaker_names)
    return "\n".join(
        f"({format_timestamp(segment.start_seconds)}) {names[segment.speaker]} : {segment.text}"
        for segment in result.segments
    )


def format_transcript_report(
    result: YouTubeTranscriptResult,
    speaker_names: Mapping[str, str] | None = None,
) -> str:
    """Return channel, spokespersons, caption provenance, and transcript as TXT."""
    names = _speaker_mapping(result, speaker_names)
    source_label = "Subtitle manual YouTube" if result.caption_source == "manual" else "Subtitle otomatis YouTube"
    spokespersons = ", ".join(dict.fromkeys(names.values()))
    return (
        f"Nama Channel: {result.channel}\n"
        f"Judul Video: {result.title}\n"
        f"Spokesperson: {spokespersons}\n"
        f"Bahasa Subtitle: {result.language_name} ({result.language_code})\n"
        f"Sumber Transcript: {source_label}\n\n"
        f"Transcript:\n{format_transcript(result, names)}"
    )
