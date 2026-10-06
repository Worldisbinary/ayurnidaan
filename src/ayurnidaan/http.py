"""One outbound-HTTP helper for the whole codebase.

Every external call (Kaggle/Orphanet downloads, Open-Meteo, Europe PMC, DigiLocker) goes
through ``open_url`` so the security policy lives in one place:

* only ``https`` is allowed (plain ``http`` only to localhost, for the local sandbox) -
  ``urllib`` would otherwise also follow ``file://`` and custom schemes (Bandit B310);
* a timeout is mandatory;
* a fixed User-Agent identifies the service to upstream APIs.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from http.client import HTTPResponse

USER_AGENT = "ayurnidaan/1.2 (+https://github.com/Worldisbinary/ayurnidaan)"
_LOCAL = {"localhost", "127.0.0.1", "::1"}


class UnsafeURL(ValueError):
    pass


def check_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" and parts.hostname:
        return url
    if parts.scheme == "http" and parts.hostname in _LOCAL:
        return url
    raise UnsafeURL(f"refusing non-https URL: {parts.scheme}://{parts.hostname}")


def open_url(
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    method: str | None = None,
    timeout: float = 30,
) -> HTTPResponse:
    req = urllib.request.Request(
        check_url(url),
        data=data,
        method=method,
        headers={"User-Agent": USER_AGENT, **(headers or {})},
    )
    # Scheme validated by check_url above.
    return urllib.request.urlopen(req, timeout=timeout)  # nosec B310


def get_json(url: str, *, headers: dict[str, str] | None = None, timeout: float = 30) -> dict:
    with open_url(url, headers=headers, timeout=timeout) as resp:
        return json.loads(resp.read())
