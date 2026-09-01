"""URL validation and SSRF safeguards."""
from __future__ import annotations
import ipaddress
import socket
from urllib.parse import urlparse

class URLValidationError(ValueError):
    pass

def validate_public_url(url: str, *, resolve_dns: bool = True) -> str:
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise URLValidationError("Masukkan URL lengkap yang diawali http:// atau https://.")
    if parsed.username or parsed.password:
        raise URLValidationError("URL yang memuat kredensial tidak diizinkan.")
    if parsed.port not in {None, 80, 443}:
        raise URLValidationError("Hanya port web standar 80 dan 443 yang diizinkan.")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith((".local", ".internal", ".localhost")):
        raise URLValidationError("Alamat lokal atau internal tidak diizinkan.")
    try:
        addresses = {ipaddress.ip_address(hostname)}
    except ValueError:
        addresses = set()
        if resolve_dns:
            try:
                addresses = {ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(hostname, None)}
            except socket.gaierror as exc:
                raise URLValidationError("Domain tidak dapat ditemukan.") from exc
    if any(not address.is_global for address in addresses):
        raise URLValidationError("URL mengarah ke jaringan privat atau alamat khusus.")
    return cleaned
