"""Request / response models. Validation here is the API's first safety layer."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from ..clinical import pariksha, red_flags

Role = Literal["patient", "practitioner"]
Sex = Literal["female", "male"]


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=2, max_length=200)
    role: Role = "patient"
    registration_number: str | None = Field(default=None, max_length=64)

    @field_validator("registration_number")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return v.strip() or None if v else None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    practitioner_verified: bool


class ProfileIn(BaseModel):
    date_of_birth: date | None = None
    sex: Sex | None = None
    state: str | None = Field(default=None, max_length=64)
    district: str | None = Field(default=None, max_length=64)
    chronic_conditions: list[str] = Field(default_factory=list, max_length=30)
    current_medicines: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("date_of_birth")
    @classmethod
    def _plausible(cls, v: date | None) -> date | None:
        if v and not (date(1900, 1, 1) <= v <= date.today()):
            raise ValueError("date_of_birth out of range")
        return v


class LocationIn(BaseModel):
    """Exact coordinates are rounded to ~11 km server-side and never stored raw."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    state: str | None = Field(default=None, max_length=64)
    district: str | None = Field(default=None, max_length=64)


class ConsentIn(BaseModel):
    purpose: Literal["care", "research", "location"]
    granted: bool


class PrakritiIn(BaseModel):
    answers: dict[str, str]


Agni = Literal[tuple(pariksha.AGNI)]  # type: ignore[valid-type]
Aggravating = Literal[tuple(pariksha.AGGRAVATING)]  # type: ignore[valid-type]
Relieving = Literal[tuple(pariksha.RELIEVING)]  # type: ignore[valid-type]
RedFlagCode = Literal[tuple(red_flags.FLAGS)]  # type: ignore[valid-type]


class EncounterCreate(BaseModel):
    red_flag_checklist: dict[RedFlagCode, bool]
    chief_complaint: str | None = Field(default=None, max_length=300)
    symptoms: dict[str, bool] = Field(default_factory=dict, max_length=120)
    free_text_symptoms: list[str] = Field(default_factory=list, max_length=20)
    aggravating: list[Aggravating] = Field(default_factory=list)
    relieving: list[Relieving] = Field(default_factory=list)
    agni: Agni | None = None

    @field_validator("red_flag_checklist")
    @classmethod
    def _complete(cls, v: dict) -> dict:
        missing = set(red_flags.FLAGS) - set(v)
        if missing:
            raise ValueError(f"red-flag checklist incomplete: {sorted(missing)}")
        return v


class AnswersIn(BaseModel):
    symptoms: dict[str, bool] = Field(default_factory=dict, max_length=60)
    free_text_symptoms: list[str] = Field(default_factory=list, max_length=20)


class ExaminationIn(BaseModel):
    examination: dict[str, str]

    @field_validator("examination")
    @classmethod
    def _known(cls, v: dict[str, str]) -> dict[str, str]:
        for f, opt in v.items():
            if f not in pariksha.EXAMINATION or opt not in pariksha.EXAMINATION[f]:
                raise ValueError(f"unknown examination finding {f}={opt}")
        return v


class ReviewIn(BaseModel):
    decision: Literal["confirmed", "revised", "ruled_out", "referred"]
    condition_id: str | None = Field(default=None, max_length=16)
    notes: str | None = Field(default=None, max_length=4000)
    plan: str | None = Field(default=None, max_length=4000)
