"""Idempotency keys for writes that must not happen twice.

Mobile networks drop responses: the app sends "create encounter", the server creates it,
the reply is lost, and the app retries. Without protection the patient now has two
encounters in the practitioner queue (or a practitioner's review is recorded twice).

The client sends ``Idempotency-Key: <random id>`` once per user action and reuses it on
retries. The server stores the response of the first successful attempt and returns it
for every retry, with ``Idempotent-Replayed: true``:

    first attempt     -> run the handler, save (user, key, request hash, response)
    retry, same body  -> return the saved response; nothing runs again
    same key, other body -> 422 (a client bug; never silently run or replay)
    two at once       -> both run, but the saved row's primary key (user_id, key) lets
                         only one transaction commit; the loser rolls back *all* of its
                         writes and replays the winner's response

The saved row is written in the **same transaction** as the business data, so there is
no window where the encounter exists but the key does not (or the reverse). Keys are
scoped per user (one user cannot replay another's response) and expire after
``TTL``. Requests without the header behave exactly as before.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .deps import DB, CurrentUser
from .models import IdempotencyKey
from .observability import IDEMPOTENT_REPLAYS

HEADER = "Idempotency-Key"
TTL = timedelta(hours=24)
_VALID = re.compile(r"^[A-Za-z0-9_.:-]{8,64}$")


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)  # SQLite returns naive datetimes


@dataclass
class IdempotentWrite:
    db: Session
    user_id: str
    route: str
    key: str | None
    request_hash: str = ""

    def replay(self, payload: dict) -> JSONResponse | None:
        """Call first. Returns the stored response for a retry, else None (go ahead)."""
        if self.key is None:
            return None
        self.request_hash = hashlib.sha256(
            json.dumps({"route": self.route, "body": payload}, sort_keys=True, default=str).encode()
        ).hexdigest()
        row = self.db.get(IdempotencyKey, (self.user_id, self.key))
        if row is None:
            return None
        if _aware(row.created_at) < datetime.now(UTC) - TTL:
            self.db.delete(row)
            self.db.flush()
            return None
        return self._from_row(row)

    def _from_row(self, row: IdempotencyKey) -> JSONResponse:
        if row.request_hash != self.request_hash or row.route != self.route:
            raise HTTPException(422, f"{HEADER} was already used for a different request")
        IDEMPOTENT_REPLAYS.labels(self.route).inc()
        return JSONResponse(
            row.response_body,
            status_code=row.status_code,
            headers={"Idempotent-Replayed": "true"},
        )

    def commit(self, status_code: int, body: dict) -> JSONResponse:
        """Save the response with the business writes in one transaction, then commit."""
        if self.key is not None:
            self.db.execute(
                delete(IdempotencyKey).where(
                    IdempotencyKey.user_id == self.user_id,
                    IdempotencyKey.created_at < datetime.now(UTC) - TTL,
                )
            )
            self.db.add(
                IdempotencyKey(
                    user_id=self.user_id,
                    key=self.key,
                    route=self.route,
                    request_hash=self.request_hash,
                    status_code=status_code,
                    response_body=body,
                )
            )
        try:
            self.db.commit()
        except IntegrityError:
            # A concurrent request with the same key committed first.
            self.db.rollback()
            row = self.db.get(IdempotencyKey, (self.user_id, self.key)) if self.key else None
            if row is None:
                raise
            return self._from_row(row)
        return JSONResponse(body, status_code=status_code)


def idempotent_write(request: Request, db: DB, user: CurrentUser) -> IdempotentWrite:
    key = request.headers.get(HEADER)
    if key is not None and not _VALID.match(key):
        raise HTTPException(400, f"{HEADER} must be 8-64 characters of [A-Za-z0-9_.:-]")
    route = request.scope.get("route")
    return IdempotentWrite(
        db, user.id, getattr(route, "path", request.url.path) + f" {request.method}", key
    )


Idempotent = Annotated[IdempotentWrite, Depends(idempotent_write)]
