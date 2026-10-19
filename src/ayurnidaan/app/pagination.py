"""Keyset ("seek") pagination with opaque cursors, and HTTP caching for reference data.

**Why keyset, not OFFSET.** ``LIMIT 50 OFFSET 5000`` makes the database walk and throw
away 5,000 rows, so deep pages get slower, and a row inserted meanwhile shifts every page
(duplicates or gaps). A keyset page instead says "rows after (a, b, c)", which the
composite index answers by seeking straight to that position: every page costs the same,
and inserts never shift pages. The sort key must be unique, so ``id`` is always the
last column.

The cursor is the last row's sort key, JSON + base64url. It is opaque to clients (they
pass back ``X-Next-Cursor``) but not secret or signed: tampering only moves the page
start within data the caller is already allowed to read.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import datetime

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse

NEXT_CURSOR = "X-Next-Cursor"
DEFAULT_LIMIT, MAX_LIMIT = 50, 200


def encode_cursor(*values) -> str:
    raw = json.dumps([v.isoformat() if isinstance(v, datetime) else v for v in values])
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, types: tuple[type, ...]) -> tuple:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        values = json.loads(raw)
        if not isinstance(values, list) or len(values) != len(types):
            raise ValueError("shape")
        return tuple(
            datetime.fromisoformat(v) if t is datetime else t(v)
            for v, t in zip(values, types, strict=True)
        )
    except (ValueError, TypeError, binascii.Error, json.JSONDecodeError):
        raise HTTPException(400, "invalid cursor") from None


def page(rows: list, limit: int, key, response: Response) -> list:
    """Trim the ``limit + 1`` probe row and set the next cursor header if there is more."""
    if len(rows) > limit:
        rows = rows[:limit]
        response.headers[NEXT_CURSOR] = encode_cursor(*key(rows[-1]))
    return rows


def cached_json(request: Request, payload, version: str, max_age: int = 300) -> Response:
    """Public reference data: a strong ETag from (version, body) plus a short max-age.

    Browsers and any CDN reuse the response for ``max_age`` seconds; after that a
    conditional request (If-None-Match) costs a 304 with no body. Only for data that is
    the same for every caller; anything per-user stays ``no-store``.
    """
    body = json.dumps(payload, separators=(",", ":"), default=str).encode()
    etag = '"' + hashlib.sha256(version.encode() + b"\0" + body).hexdigest()[:32] + '"'
    headers = {"ETag": etag, "Cache-Control": f"public, max-age={max_age}"}
    if etag in request.headers.get("if-none-match", ""):
        return Response(status_code=304, headers=headers)
    return JSONResponse(payload, headers=headers)
