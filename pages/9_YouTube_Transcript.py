# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

"""MIDETA single-URL YouTube transcript workspace."""
from __future__ import annotations

import hashlib
import re

import streamlit as st

from src.config import MIDETA_LOGO_PATH
from src.ui import apply_theme, page_intro, render_footer, render_github_profile
from src.youtube_transcript import (
    YouTubeTranscriptCollector,
    YouTubeTranscriptError,
    format_transcript,
    format_transcript_metadata,
    format_transcript_report,
)


LANGUAGE_OPTIONS = {
    "Otomatis (utamakan Indonesia)": "auto",
    "Indonesia": "id",
    "English": "en",
}


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "").strip()).strip("-")
    return (cleaned[:80] or "youtube-transcript") + ".txt"


st.set_page_config(
    page_title="YouTube Transcript | MIDETA",
    page_icon=str(MIDETA_LOGO_PATH),
    layout="wide",
)
apply_theme()
render_github_profile()
page_intro(
    "09",
    "YouTube Transcript",
    "Proses satu URL menjadi channel, daftar spokesperson, dan transcript bertimestamp.",
)

st.info(
    "Versi awal memakai subtitle manual atau otomatis yang disediakan YouTube dan tidak mengunduh videonya. "
    "Nama spokesperson dibaca hanya bila caption memuat label pembicara; label yang tidak tersedia dapat Anda rename setelah proses."
)

st.markdown('<div class="section-label">LANGKAH 1 · MASUKKAN VIDEO</div>', unsafe_allow_html=True)
with st.form("youtube_transcript_form"):
    url_value = st.text_input(
        "URL YouTube",
        placeholder="https://www.youtube.com/watch?v=...",
        help="Masukkan satu URL video, Shorts, atau live replay YouTube per proses.",
    )
    language_label = st.selectbox(
        "Bahasa subtitle",
        list(LANGUAGE_OPTIONS),
        help=(
            "Otomatis mengutamakan subtitle Indonesia, lalu English, kemudian bahasa lain yang tersedia. "
            "MIDETA tidak menerjemahkan isi transcript."
        ),
    )
    submitted = st.form_submit_button(
        "Proses Transcript",
        type="primary",
        icon=":material/subtitles:",
        width="stretch",
    )

if submitted:
    st.session_state.pop("youtube_transcript_result", None)
    progress = st.progress(0.01, text="YouTube Transcript · Menyiapkan proses · 1%")

    def update_progress(fraction: float, detail: str) -> None:
        safe_fraction = min(max(float(fraction), 0.0), 1.0)
        progress.progress(
            safe_fraction,
            text=f"YouTube Transcript · {detail} · {round(safe_fraction * 100)}%",
        )

    try:
        result = YouTubeTranscriptCollector().collect(
            url_value,
            language=LANGUAGE_OPTIONS[language_label],
            progress_callback=update_progress,
        )
    except YouTubeTranscriptError as exc:
        progress.progress(1.0, text="YouTube Transcript · Proses berhenti · 100%")
        st.error(f"Transcript gagal diproses: {exc}")
    else:
        st.session_state["youtube_transcript_result"] = result
        st.success(f"Transcript selesai diproses · {len(result.segments):,} baris.")

result = st.session_state.get("youtube_transcript_result")
if result is not None:
    st.markdown('<div class="section-label">LANGKAH 2 · PERIKSA IDENTITAS</div>', unsafe_allow_html=True)
    first, second, third = st.columns(3)
    first.metric("Nama Channel", result.channel)
    second.metric("Spokesperson", str(len(result.spokespersons)))
    third.metric("Baris Transcript", f"{len(result.segments):,}")

    with st.container(border=True):
        st.markdown(f"#### {result.title}")
        source_label = (
            "Subtitle manual YouTube"
            if result.caption_source == "manual"
            else "Subtitle otomatis YouTube"
        )
        st.caption(
            f"{source_label} · {result.language_name} ({result.language_code}) · "
            "timestamp dibulatkan ke detik awal setiap cue."
        )
        st.link_button(
            "Buka Video YouTube",
            result.source_url,
            icon=":material/open_in_new:",
        )

    generic_speakers = [
        speaker
        for speaker in result.spokespersons
        if re.fullmatch(r"Pembicara \d+", speaker, re.I)
    ]
    if generic_speakers:
        st.warning(
            "Caption YouTube tidak menyertakan nama untuk semua pembicara. "
            "Ganti label Pembicara di bawah jika Anda mengenali orangnya."
        )
    elif result.has_named_speakers:
        st.success("Nama spokesperson ditemukan dari label pembicara di caption YouTube.")

    speaker_names: dict[str, str] = {}
    identity = hashlib.sha1(result.source_url.encode("utf-8")).hexdigest()[:10]
    name_columns = st.columns(min(3, max(1, len(result.spokespersons))))
    for index, speaker in enumerate(result.spokespersons):
        with name_columns[index % len(name_columns)]:
            speaker_names[speaker] = st.text_input(
                f"Nama untuk {speaker}",
                value=speaker,
                key=f"youtube_speaker_{identity}_{index}",
            ).strip() or speaker

    metadata = format_transcript_metadata(result, speaker_names)
    transcript = format_transcript(result, speaker_names)
    report = format_transcript_report(result, speaker_names)
    st.markdown('<div class="section-label">LANGKAH 3 · COPY ATAU UNDUH</div>', unsafe_allow_html=True)
    metadata_column, transcript_column = st.columns([0.36, 0.64], gap="large")
    with metadata_column:
        st.markdown("#### Informasi Video")
        st.code(metadata, language=None, wrap_lines=True)
    with transcript_column:
        st.markdown("#### Transcript")
        st.code(transcript, language=None, wrap_lines=True)
    st.download_button(
        "Unduh Transcript TXT",
        data=report.encode("utf-8-sig"),
        file_name=safe_filename(result.title),
        mime="text/plain",
        icon=":material/download:",
        type="primary",
        width="stretch",
    )
    st.caption(
        "Format baris: (00:00:00) Nama : Kalimat. Periksa kembali ejaan nama, istilah, dan hasil subtitle otomatis sebelum dipakai dalam laporan final."
    )

render_footer()
