"""Conservative public-page fetcher with redirect revalidation."""
from __future__ import annotations
import requests
from src.config import MAX_REDIRECTS, MAX_RESPONSE_BYTES, REQUEST_TIMEOUT_SECONDS
from src.validators import validate_public_url

USER_AGENT = "Mozilla/5.0 (compatible; MIDETA/1.0; local media intelligence)"

class CollectionError(RuntimeError):
    pass

def fetch_public_html(url: str) -> tuple[str, str]:
    current = validate_public_url(url)
    for _ in range(MAX_REDIRECTS + 1):
        try:
            response = requests.get(current, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False, stream=True)
        except requests.RequestException as exc:
            raise CollectionError(f"Halaman tidak dapat dihubungi: {exc}") from exc
        if response.is_redirect or response.is_permanent_redirect:
            target = response.headers.get("location")
            response.close()
            if not target:
                raise CollectionError("Situs memberikan pengalihan tanpa tujuan.")
            current = requests.compat.urljoin(current, target)
            validate_public_url(current)
            continue
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            code = response.status_code
            response.close()
            if code in {401, 403}:
                raise CollectionError("Akses ditolak. Halaman mungkin memerlukan login atau dilindungi situs.") from exc
            if code == 429:
                raise CollectionError("Permintaan dibatasi oleh situs. Coba lagi nanti tanpa melewati rate limit.") from exc
            raise CollectionError(f"Situs mengembalikan HTTP {code}.") from exc
        content_type = response.headers.get("content-type", "").lower()
        if "html" not in content_type:
            response.close()
            raise CollectionError("URL tidak mengembalikan halaman HTML.")
        declared = int(response.headers.get("content-length", "0") or 0)
        if declared > MAX_RESPONSE_BYTES:
            response.close()
            raise CollectionError("Ukuran halaman melebihi batas 8 MB.")
        chunks, total = [], 0
        for chunk in response.iter_content(64 * 1024):
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                response.close()
                raise CollectionError("Ukuran halaman melebihi batas 8 MB.")
            chunks.append(chunk)
        encoding = response.encoding or "utf-8"
        final_url = response.url
        response.close()
        return b"".join(chunks).decode(encoding, errors="replace"), final_url
    raise CollectionError("Terlalu banyak pengalihan URL.")
