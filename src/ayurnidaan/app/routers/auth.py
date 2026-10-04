from __future__ import annotations

from datetime import timedelta

import jwt
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from ..deps import DB, AppSettings, CurrentUser
from ..models import PatientProfile, User
from ..schemas import LoginIn, RefreshIn, RegisterIn, TokenOut, UserOut
from ..security import decode_token, hash_password, make_token, verify_password
from ..services import audit

router = APIRouter(prefix="/auth", tags=["auth"])
# Verified against when the email is unknown, so both paths cost one full scrypt.
_DUMMY_HASH = hash_password("not-a-real-password")


def _tokens(settings, user: User) -> TokenOut:
    access = make_token(
        settings.jwt_secret,
        user.id,
        "access",
        timedelta(minutes=settings.access_token_minutes),
        user.role,
        user.token_version,
    )
    refresh = make_token(
        settings.jwt_secret,
        user.id,
        "refresh",
        timedelta(days=settings.refresh_token_days),
        user.role,
        user.token_version,
    )
    return TokenOut(access_token=access, refresh_token=refresh, role=user.role)


def user_out(u: User) -> UserOut:
    return UserOut(
        id=u.id,
        email=u.email,
        full_name=u.full_name,
        role=u.role,
        practitioner_verified=u.practitioner_verified,
    )


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, db: DB, settings: AppSettings) -> TokenOut:
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered")
    if body.role == "practitioner" and not body.registration_number:
        raise HTTPException(422, "practitioners must provide their registration number")
    role = (
        "admin"
        if settings.bootstrap_admin_email and email == settings.bootstrap_admin_email.lower()
        else body.role
    )
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        role=role,
        registration_number=body.registration_number,
    )
    if role == "patient":
        user.profile = PatientProfile()
    db.add(user)
    db.flush()
    audit(db, user.id, "auth.register", "user", user.id, role=role)
    db.commit()
    return _tokens(settings, user)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: DB, settings: AppSettings) -> TokenOut:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    # Same error and (scrypt) cost whether the email exists or not: no account enumeration.
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid email or password")
    audit(db, user.id, "auth.login", "user", user.id)
    db.commit()
    return _tokens(settings, user)


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, db: DB, settings: AppSettings) -> TokenOut:
    try:
        payload = decode_token(settings.jwt_secret, body.refresh_token, "refresh")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh token") from None
    user = db.get(User, payload["sub"])
    if not user or not user.is_active or payload.get("tv") != user.token_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh token")
    return _tokens(settings, user)


@router.post("/logout-all", status_code=204)
def logout_all(user: CurrentUser, db: DB) -> None:
    """Revoke every refresh token issued to this account."""
    user.token_version += 1
    audit(db, user.id, "auth.logout_all", "user", user.id)
    db.commit()


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return user_out(user)
