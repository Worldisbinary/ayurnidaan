"""DigiLocker identity connector (OAuth 2.0 authorization code + PKCE).

Prefills date of birth, sex, state and district from the user's DigiLocker account so
the intake stays minimal. Only those derived fields are kept: the Aadhaar number, the
eAadhaar document and the photo are never stored (Aadhaar Act s.29; DPDP minimisation).

Modes (``AYUR_DIGILOCKER_MODE``):

* ``sandbox``    - a local consent screen returns a configurable test identity, so the
                   whole flow works end to end without partner credentials (default
                   outside production);
* ``production`` - DigiLocker's partner API. Requires onboarding as a DigiLocker
                   *Requester* with NeGD (an organisation, not an individual), which issues
                   the client id / secret. Endpoint URLs are settings: confirm them against
                   the partner API specification you receive at onboarding;
* ``disabled``   - the feature is hidden.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import re
import secrets
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime

from defusedxml import ElementTree as ET  # XXE / billion-laughs safe

from ..config import Settings
from ..http import open_url


@dataclass(frozen=True)
class Identity:
    name: str | None
    dob: date | None
    sex: str | None  # female | male | other
    state: str | None
    district: str | None


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    return verifier, challenge


def _parse_dob(text: str | None) -> date | None:
    if not text:
        return None
    for fmt in ("%d%m%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


_SEX = {"m": "male", "male": "male", "f": "female", "female": "female", "t": "other", "o": "other"}


def parse_user_details(payload: dict) -> Identity:
    """DigiLocker /user response: {"name", "dob" (DDMMYYYY), "gender" (M/F/T), ...}."""
    return Identity(
        name=payload.get("name"),
        dob=_parse_dob(payload.get("dob")),
        sex=_SEX.get(str(payload.get("gender", "")).strip().lower()),
        state=None,
        district=None,
    )


def parse_eaadhaar_address(xml_text: str) -> tuple[str | None, str | None]:
    """State and district from the eAadhaar XML <Poa> element; nothing else is read."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None, None
    for el in root.iter():
        if el.tag.split("}")[-1] == "Poa":
            return el.attrib.get("state") or None, el.attrib.get("dist") or None
    return None, None


def names_match(a: str | None, b: str | None) -> bool | None:
    if not a or not b:
        return None
    norm = lambda s: set(re.sub(r"[^a-z ]", "", s.casefold()).split())  # noqa: E731
    return len(norm(a) & norm(b)) >= min(2, len(norm(b)))


def allowed_return(settings: Settings, url: str) -> bool:
    """Only redirect back to our own app: a configured web origin or the app's scheme."""
    prefixes = [o.rstrip("/") + "/" for o in settings.cors_origins] + ["ayurnidaan://", "exp://"]
    return any(url.startswith(p) or url.rstrip("/") + "/" == p for p in prefixes)


class SandboxProvider:
    mode = "sandbox"

    def __init__(self, settings: Settings):
        self.settings = settings

    def callback_url(self) -> str:
        return f"{self.settings.public_api_url.rstrip('/')}/api/v1/digilocker/callback"

    def authorize_url(self, state: str, challenge: str) -> str:
        q = urllib.parse.urlencode(
            {"state": state, "code_challenge": challenge, "redirect_uri": self.callback_url()}
        )
        return f"{self.settings.public_api_url.rstrip('/')}/api/v1/digilocker/sandbox/authorize?{q}"

    def exchange(self, code: str, verifier: str) -> str:
        if not code.startswith("sandbox-"):
            raise ValueError("invalid sandbox authorization code")
        return "sandbox-token"

    def identity(self, token: str, account_name: str | None = None) -> Identity:
        p = self.settings.digilocker_sandbox_identity
        return Identity(
            name=account_name or p.get("name"),
            dob=_parse_dob(p.get("dob")),
            sex=_SEX.get(str(p.get("gender", "")).lower()),
            state=p.get("state"),
            district=p.get("district"),
        )


class ProductionProvider:
    mode = "production"

    def __init__(self, settings: Settings):
        if not (settings.digilocker_client_id and settings.digilocker_client_secret):
            raise RuntimeError("DigiLocker production mode needs client id and secret")
        self.s = settings

    def callback_url(self) -> str:
        return self.s.digilocker_redirect_uri or (
            f"{self.s.public_api_url.rstrip('/')}/api/v1/digilocker/callback"
        )

    def authorize_url(self, state: str, challenge: str) -> str:
        q = urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": self.s.digilocker_client_id,
                "redirect_uri": self.callback_url(),
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{self.s.digilocker_authorize_url}?{q}"

    def exchange(self, code: str, verifier: str) -> str:
        body = urllib.parse.urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.callback_url(),
                "client_id": self.s.digilocker_client_id,
                "client_secret": self.s.digilocker_client_secret,
                "code_verifier": verifier,
            }
        ).encode()
        with open_url(
            self.s.digilocker_token_url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20,
        ) as resp:
            return json.loads(resp.read())["access_token"]

    def _get(self, url: str, token: str) -> bytes:
        with open_url(url, headers={"Authorization": f"Bearer {token}"}, timeout=20) as resp:
            return resp.read()

    def identity(self, token: str, account_name: str | None = None) -> Identity:
        ident = parse_user_details(json.loads(self._get(self.s.digilocker_user_url, token)))
        state = district = None
        with contextlib.suppress(Exception):  # address is optional; never fail the link over it
            state, district = parse_eaadhaar_address(
                self._get(self.s.digilocker_eaadhaar_url, token).decode()
            )
        return Identity(ident.name, ident.dob, ident.sex, state, district)


def provider(settings: Settings):
    mode = settings.digilocker_effective_mode
    if mode == "production":
        return ProductionProvider(settings)
    if mode == "sandbox":
        return SandboxProvider(settings)
    return None


SANDBOX_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>DigiLocker (sandbox)</title>
<style>body{{font-family:system-ui,sans-serif;background:#f4f6fa;margin:0;padding:24px}}
.card{{max-width:420px;margin:40px auto;background:#fff;border-radius:10px;padding:24px;
box-shadow:0 2px 12px rgba(0,0,0,.08)}}h1{{font-size:20px;margin:0 0 4px}}.tag{{display:inline-block;
background:#fff3cd;color:#7a5b00;border-radius:4px;padding:2px 8px;font-size:12px}}
li{{margin:6px 0}}.row{{display:flex;gap:10px;margin-top:20px}}a{{flex:1;text-align:center;
padding:10px;border-radius:6px;text-decoration:none;font-weight:600}}.allow{{background:#1c5cab;
color:#fff}}.deny{{background:#eee;color:#222}}</style></head><body><div class="card">
<span class="tag">SANDBOX - test identity, not a real DigiLocker account</span>
<h1>Share details with Ayurnidaan?</h1><p>Ayurnidaan is requesting:</p><ul>
<li>Name, date of birth and gender</li><li>State and district from your address</li></ul>
<p style="font-size:13px;color:#555">Your Aadhaar number and documents are not stored.</p>
<div class="row"><a class="deny" href="{deny}">Deny</a><a class="allow" href="{allow}">Allow</a>
</div></div></body></html>"""
