"""FastAPI dependencies: DB session, current user, role guards."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..config import Settings
from .models import User
from .security import decode_token
from .services import ClinicalService

bearer = HTTPBearer(auto_error=False)


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    yield from request.app.state.db.session()


def get_clinical(request: Request) -> ClinicalService:
    return request.app.state.clinical


DB = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings_dep)]
Clinical = Annotated[ClinicalService, Depends(get_clinical)]


def current_user(
    db: DB,
    settings: AppSettings,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "not authenticated", headers={"WWW-Authenticate": "Bearer"}
    )
    if creds is None:
        raise unauthorized
    try:
        payload = decode_token(settings.jwt_secret, creds.credentials, "access")
    except jwt.PyJWTError:
        raise unauthorized from None
    user = db.get(User, payload["sub"])
    if user is None or not user.is_active or payload.get("tv") != user.token_version:
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require(*roles: str, verified: bool = False) -> Callable[[User], User]:
    def guard(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient role")
        if verified and user.role == "practitioner" and not user.practitioner_verified:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "practitioner registration not yet verified"
            )
        return user

    return guard


Patient = Annotated[User, Depends(require("patient"))]
Practitioner = Annotated[User, Depends(require("practitioner", verified=True))]
Admin = Annotated[User, Depends(require("admin"))]
