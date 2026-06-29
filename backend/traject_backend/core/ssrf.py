"""SSRF protection for server-initiated outbound requests.

User-controlled URLs that the *backend* fetches (e.g. budget alert webhooks)
must not be allowed to target internal infrastructure or cloud metadata. This
module validates such URLs before any request is made.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

# Cloud metadata endpoints (AWS/GCP/Azure) — always blocked.
_METADATA_HOSTS = {"169.254.169.254", "metadata.google.internal", "fd00:ec2::254"}


class SSRFValidationError(ValueError):
    """Raised when a URL is rejected as an SSRF risk."""


def validate_external_url(url: str, *, require_https: bool = True) -> None:
    """Validate that *url* is safe for the server to call, or raise.

    Rejects non-HTTP(S) schemes, (optionally) plaintext HTTP, and any host that
    resolves to a private, loopback, link-local, reserved, or multicast IP, plus
    known cloud-metadata endpoints.

    Args:
        url: The user-supplied URL the backend would request.
        require_https: When True (default) only ``https`` is allowed.

    Raises:
        SSRFValidationError: If the URL is malformed or targets a disallowed host.
    """
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if require_https:
        if scheme != "https":
            raise SSRFValidationError("Webhook URL must use https")
    elif scheme not in ("http", "https"):
        raise SSRFValidationError(f"Unsupported URL scheme: {scheme!r}")

    host = parsed.hostname
    if not host:
        raise SSRFValidationError("URL has no host")
    if host.lower() in _METADATA_HOSTS:
        raise SSRFValidationError("URL targets a cloud metadata endpoint")

    # Resolve every address the host maps to and reject if any is non-public.
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if scheme == "https" else 80))
    except OSError as exc:
        raise SSRFValidationError(f"Could not resolve host {host!r}") from exc

    for info in infos:
        ip_str = info[4][0]
        ip = ipaddress.ip_address(ip_str)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise SSRFValidationError(
                f"URL host {host!r} resolves to disallowed address {ip_str}"
            )
