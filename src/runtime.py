"""Runtime capability helpers shared by the Streamlit pages."""
from __future__ import annotations

import os
from urllib.parse import urlparse


_TRUE_VALUES = {"1", "true", "yes", "on", "enabled", "local"}
_FALSE_VALUES = {"0", "false", "no", "off", "disabled", "remote", "cloud"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "testserver"}


def browser_sessions_available(page_url: str | None = None) -> bool:
    """Return whether the Streamlit server can open an interactive local Chrome.

    A browser launched by Selenium always opens beside the Streamlit *server*.
    That is useful for a local desktop run, but cannot open the visitor's Chrome
    when the app is hosted on Streamlit Community Cloud. An environment
    override keeps self-hosted desktop installations configurable.
    """
    override = os.environ.get("MIDETA_BROWSER_SESSIONS", "").strip().casefold()
    if override in _TRUE_VALUES:
        return True
    if override in _FALSE_VALUES:
        return False

    raw_url = str(page_url or "").strip()
    if not raw_url:
        # CLI utilities and Streamlit AppTest do not always expose a request
        # URL. Keep the established local behavior in that case.
        return True
    parsed = urlparse(raw_url if "://" in raw_url else f"//{raw_url}")
    host = (parsed.hostname or "").casefold()
    return host in _LOCAL_HOSTS or host.endswith(".localhost") or host.endswith(".local")
