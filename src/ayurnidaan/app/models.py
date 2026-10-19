"""ORM models. Health data minimisation is enforced here: no free-text address, exact
GPS is never stored (coordinates are rounded to 0.1 degree, about 11 km), and every
patient-linked row cascades on account erasure."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), index=True)  # patient | practitioner | admin
    full_name: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # practitioners only: State/NCISM registration number, verified by an admin
    registration_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    practitioner_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    token_version: Mapped[int] = mapped_column(Integer, default=0)  # bump to revoke refresh tokens
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    profile: Mapped[PatientProfile | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class PatientProfile(Base):
    __tablename__ = "patient_profiles"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    sex: Mapped[str | None] = mapped_column(String(8), nullable=True)
    state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    district: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lat_round: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon_round: Mapped[float | None] = mapped_column(Float, nullable=True)
    desha: Mapped[str | None] = mapped_column(String(16), nullable=True)
    climate: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    prakriti_answers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    prakriti_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    chronic_conditions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    current_medicines: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Optional assessment modules: {module_id: {answers, result, completed_at, history[]}}
    modules: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Identity verification (DigiLocker): source, verified_at, which fields were filled.
    # Never the Aadhaar number or any document.
    identity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    user: Mapped[User] = relationship(back_populates="profile")


class Consent(Base):
    """Append-only consent ledger (DPDP Act 2023). Latest row per purpose is in force."""

    __tablename__ = "consents"
    # current_consents(): WHERE user_id = ? ORDER BY id -> one ordered index range scan.
    __table_args__ = (Index("ix_consents_user_id_id", "user_id", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(32))  # care | research | location
    granted: Mapped[bool] = mapped_column(Boolean)
    policy_version: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


TRIAGE_RANK = {"emergency": 0, "urgent": 1, "routine": 2}


class Encounter(Base):
    __tablename__ = "encounters"
    # Indexes are shaped by the two hot queries (docs/SYSTEM_DESIGN.md, "Data model"):
    #  * practitioner queue: WHERE status = ? ORDER BY triage_rank, created_at, id
    #    -> the index already holds rows in queue order, so the database reads the first
    #       page and stops (no sort), and keyset pagination continues from a cursor.
    #  * a patient's encounters: WHERE patient_id = ? ORDER BY created_at DESC, id DESC
    __table_args__ = (
        Index("ix_encounters_queue", "status", "triage_rank", "created_at", "id"),
        Index("ix_encounters_patient_created", "patient_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    patient_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    practitioner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="draft")
    # draft -> submitted -> reviewed ; or emergency (red flag, never queued as routine)
    triage_level: Mapped[str] = mapped_column(String(16), default="routine")
    # 0 emergency, 1 urgent, 2 routine: a sortable copy of triage_level for the queue index
    triage_rank: Mapped[int] = mapped_column(SmallInteger, default=2, server_default="2")
    chief_complaint: Mapped[str | None] = mapped_column(String(300), nullable=True)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    assessment: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    engine_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ritu: Mapped[str | None] = mapped_column(String(16), nullable=True)
    desha: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    reviews: Mapped[list[Review]] = relationship(
        back_populates="encounter", cascade="all, delete-orphan"
    )
    patient: Mapped[User] = relationship(foreign_keys=[patient_id], viewonly=True)


class Review(Base):
    """A practitioner's verdict on an encounter - the label the learning loop trains on."""

    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    encounter_id: Mapped[str] = mapped_column(
        ForeignKey("encounters.id", ondelete="CASCADE"), index=True
    )
    practitioner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decision: Mapped[str] = mapped_column(String(16))  # confirmed | revised | ruled_out | referred
    condition_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    condition_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    examination: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    encounter: Mapped[Encounter] = relationship(back_populates="reviews")


class ModelVersion(Base):
    """Learning-loop releases: which confirmed cases a model was fit on and how it scored."""

    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(64), unique=True)
    pack_version: Mapped[str] = mapped_column(String(32))
    n_cases: Mapped[int] = mapped_column(Integer)
    case_ids: Mapped[list] = mapped_column(JSON)
    metrics: Mapped[dict] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LocationClimate(Base):
    """Cache of Open-Meteo climate lookups per 0.1-degree cell (no personal data)."""

    __tablename__ = "location_climate"

    cell: Mapped[str] = mapped_column(String(32), primary_key=True)  # "lat,lon" rounded
    annual_precip_mm: Mapped[float] = mapped_column(Float)
    mean_rh: Mapped[float] = mapped_column(Float)
    mean_temp_c: Mapped[float] = mapped_column(Float)
    desha: Mapped[str] = mapped_column(String(16))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DailyLog(Base):
    """One Dinacharya + diet check-in per patient per day."""

    __tablename__ = "daily_logs"
    # The unique (user_id, day) index serves every query on this table (one day, or a
    # user's days in order), so separate user_id / day indexes would only slow writes.
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_daily_user_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    dinacharya: Mapped[dict] = mapped_column(JSON, default=dict)
    meals: Mapped[dict] = mapped_column(JSON, default=dict)
    score: Mapped[int] = mapped_column(Integer, default=0)
    analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class OAuthState(Base):
    """Short-lived state for third-party sign-in (DigiLocker): CSRF state + PKCE verifier."""

    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32))
    code_verifier: Mapped[str] = mapped_column(String(128))
    return_to: Mapped[str] = mapped_column(String(500))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class IdempotencyKey(Base):
    """Stored outcome of a write sent with an ``Idempotency-Key`` header (see idempotency.py).

    The primary key (user_id, key) is the concurrency guard: two racing requests with the
    same key cannot both commit, so a retried "create" can never create twice.
    """

    __tablename__ = "idempotency_keys"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    route: Mapped[str] = mapped_column(String(120))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
