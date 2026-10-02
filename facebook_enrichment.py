# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

"""Command-line Facebook enrichment powered by MIDETA.

The script never asks for or stores a Facebook password. Advanced mode reuses
the dedicated local Chrome profile managed by MIDETA; authentication happens
only inside Chrome.

Examples
--------
Fast enrichment without login::

    python facebook_enrichment.py facebook_urls.txt --mode fast

Open the dedicated Facebook login session::

    python facebook_enrichment.py --login

Advanced enrichment after login::

    python facebook_enrichment.py facebook_urls.txt --mode advanced \
        --output facebook_enrichment.xlsx
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from typing import Iterable

from src.batch import (
    compact_social_all_export_row,
    failed_social_result,
    merge_facebook_advanced_result,
    parse_social_input_rows,
)
from src.comment_browser import (
    CommentBrowserCollector,
    CommentBrowserError,
    CommentBrowserLoginRequired,
)
from src.connectors import get_platform_connector
from src.exporters import to_csv_bytes, to_xlsx_bytes
from src.models import SocialResult
from src.social_urls import (
    canonical_social_url,
    platform_from_url,
    resolve_social_url,
)


DEFAULT_OUTPUT = Path("mideta_facebook_enrichment.xlsx")


def read_input_urls(input_file: Path | None, direct_urls: Iterable[str]) -> list[str]:
    """Read one URL per row while preserving duplicate rows and their order."""
    chunks = [str(value) for value in direct_urls if str(value).strip()]
    if input_file is not None:
        chunks.append(input_file.read_text(encoding="utf-8-sig"))
    return parse_social_input_rows("\n".join(chunks), preserve_repeated_rows=True)


def collect_facebook_url(
    source_url: str,
    *,
    mode: str = "fast",
    browser: CommentBrowserCollector | None = None,
) -> SocialResult:
    """Enrich one Facebook URL and keep the exact pasted URL in the output."""
    original_url = str(source_url or "").strip()
    if platform_from_url(original_url) != "Facebook":
        return failed_social_result(
            original_url,
            "Facebook",
            "Baris ini bukan URL Facebook yang didukung.",
        )

    try:
        resolved_url = resolve_social_url(original_url, expected_platform="Facebook")
        processing_url = canonical_social_url(resolved_url, "Facebook") or resolved_url
        connector = get_platform_connector(processing_url, "Facebook")
        result = connector.enrich(processing_url)

        if mode == "advanced":
            if browser is None:
                raise CommentBrowserLoginRequired(
                    "Advanced mode membutuhkan sesi Chrome Facebook MIDETA."
                )
            browser_result = browser.collect_facebook_enrichment(processing_url)
            result = merge_facebook_advanced_result(result, browser_result)

        # A resolved share/short URL is only used internally. The spreadsheet
        # row remains identical to the manager's source list.
        result.url = original_url
        return result
    except (CommentBrowserError, ValueError, RuntimeError) as exc:
        return failed_social_result(original_url, "Facebook", str(exc))


def collect_facebook_urls(
    urls: list[str],
    *,
    mode: str,
    browser: CommentBrowserCollector | None = None,
    workers: int = 4,
) -> list[SocialResult]:
    """Process Fast URLs concurrently and Advanced URLs sequentially."""
    if mode == "advanced":
        results = []
        for index, url in enumerate(urls, start=1):
            print(f"[{index}/{len(urls)}] {url}")
            results.append(collect_facebook_url(url, mode=mode, browser=browser))
        return results

    worker_count = max(1, min(int(workers), 8, len(urls) or 1))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = list(
            executor.map(
                lambda url: collect_facebook_url(url, mode="fast"),
                urls,
            )
        )
    for index, url in enumerate(urls, start=1):
        print(f"[{index}/{len(urls)}] selesai: {url}")
    return results


def write_results(results: list[SocialResult], output_path: Path) -> Path:
    """Write a spreadsheet-friendly CSV or XLSX using MIDETA's output schema."""
    records = [compact_social_all_export_row(result) for result in results]
    suffix = output_path.suffix.casefold()
    if suffix not in {".csv", ".xlsx"}:
        raise ValueError("Output harus memakai ekstensi .csv atau .xlsx.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        to_csv_bytes(records)
        if suffix == ".csv"
        else to_xlsx_bytes(records, sheet_name="Facebook Enrichment")
    )
    output_path.write_bytes(payload)
    return output_path.resolve()


def open_login_session(browser: CommentBrowserCollector) -> bool:
    """Let the user authenticate only inside the dedicated Chrome window."""
    already_logged_in = browser.open_login()
    if already_logged_in:
        print("Sesi Facebook sudah login.")
        return True
    print("Login Facebook di jendela Chrome MIDETA yang terbuka.")
    input("Setelah login selesai, tekan Enter di terminal untuk memeriksa sesi... ")
    logged_in = browser.is_logged_in(open_platform=False)
    print("Login berhasil." if logged_in else "Login belum terdeteksi.")
    return logged_in


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Enrichment banyak URL Facebook ke CSV/XLSX dengan urutan input tetap terjaga."
        )
    )
    parser.add_argument(
        "input_file",
        nargs="?",
        type=Path,
        help="File TXT/CSV sederhana berisi satu URL Facebook per baris.",
    )
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="URL Facebook langsung; opsi ini boleh dipakai berulang.",
    )
    parser.add_argument(
        "--mode",
        choices=("fast", "advanced"),
        default="fast",
        help="Fast tanpa login; Advanced memakai sesi Chrome Facebook untuk Views.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Lokasi output .csv atau .xlsx.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Jumlah URL Fast yang diproses paralel (1-8).",
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help="Buka atau perbarui sesi login Facebook lokal sebelum enrichment.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    browser: CommentBrowserCollector | None = None
    try:
        if args.login or args.mode == "advanced":
            browser = CommentBrowserCollector("Facebook")

        if args.login and browser is not None and not open_login_session(browser):
            return 2

        urls = read_input_urls(args.input_file, args.url)
        if not urls:
            if args.login:
                return 0
            print("Tidak ada URL. Isi input_file atau gunakan --url.", file=sys.stderr)
            return 2

        if args.mode == "advanced" and browser is not None and not args.login:
            if not browser.is_logged_in():
                print(
                    "Sesi Facebook belum login. Jalankan: "
                    "python facebook_enrichment.py --login",
                    file=sys.stderr,
                )
                return 2

        results = collect_facebook_urls(
            urls,
            mode=args.mode,
            browser=browser,
            workers=args.workers,
        )
        output_path = write_results(results, args.output)
        readable = sum(
            1
            for result in results
            if any(
                field.value not in (None, "")
                for field in (
                    result.username,
                    result.caption,
                    result.posted_at,
                    result.likes,
                    result.comments,
                    result.shares,
                    result.views,
                )
            )
        )
        print(f"Selesai: {readable}/{len(results)} URL memiliki data terbaca.")
        print(f"Output: {output_path}")
        return 0
    except (OSError, ValueError, CommentBrowserError) as exc:
        print(f"Gagal: {exc}", file=sys.stderr)
        return 1
    finally:
        if browser is not None:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
