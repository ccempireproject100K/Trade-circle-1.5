from datetime import date
from enum import Enum
from typing import Annotated, Literal

import re

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    TypeAdapter,
    field_validator,
    model_validator,
)

TRADES = (
    "electrician",
    "plumber",
    "hvac",
    "roofer",
    "carpenter",
    "painter",
    "landscaper",
    "mason",
    "flooring",
    "general_contractor",
    "handyman",
    "other",
)

E164 = r"^\+[1-9]\d{7,14}$"


def _normalize_phone(value):
    """Accept how people type US numbers, e.g. (512) 555-0199, and store E.164."""
    if not isinstance(value, str):
        return value
    digits = re.sub(r"\D", "", value)
    if value.strip().startswith("+"):
        return "+" + digits
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return value


Phone = Annotated[str, BeforeValidator(_normalize_phone), Field(pattern=E164)]
_email = TypeAdapter(EmailStr)
ShortText = Annotated[str, Field(min_length=1, max_length=120)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _check_trade(value: str | None) -> str | None:
    if value is None:
        return value
    value = value.lower()
    if value not in TRADES:
        raise ValueError(f"trade must be one of: {', '.join(TRADES)}")
    return value


def _https_only(value: HttpUrl | None) -> HttpUrl | None:
    if value is not None and value.scheme != "https":
        raise ValueError("must be an https URL")
    return value


# --- auth ---


class SignupIn(Strict):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    business_name: ShortText
    trade: str
    city: ShortText
    ref: Annotated[str, Field(max_length=16)] | None = None  # referral code from a member's link

    _trade = field_validator("trade")(_check_trade)


class LoginIn(Strict):
    email: EmailStr
    password: str = Field(max_length=128)


class PasswordChangeIn(Strict):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


# --- profile ---


class License(Strict):
    name: ShortText
    number: Annotated[str, Field(max_length=60)] = ""
    issuer: Annotated[str, Field(max_length=120)] = ""
    expires_on: date
    renewed_on: date | None = None


class ProfileUpdate(Strict):
    """Omitted fields stay as they are; null clears a field that is optional."""

    published: bool | None = None
    business_name: ShortText | None = None
    tagline: Annotated[str, Field(max_length=140)] | None = None
    about: Annotated[str, Field(max_length=4000)] | None = None
    trade: str | None = None
    city: ShortText | None = None
    service_area: Annotated[str, Field(max_length=200)] | None = None
    phone: Phone | None = None
    # Apple ID email or phone used for the FaceTime button.
    facetime: Annotated[str, Field(max_length=120)] | None = None
    brand_color: Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")] | None = None
    layout: list[str] | None = Field(default=None, max_length=20)
    licenses: list[License] | None = Field(default=None, max_length=20)

    _trade = field_validator("trade")(_check_trade)

    @field_validator("facetime")
    @classmethod
    def _facetime_contact(cls, value: str | None) -> str | None:
        if value is None:
            return value
        phone = _normalize_phone(value)
        if re.fullmatch(E164, phone):
            return phone
        return _email.validate_python(value)


class InsuranceIn(Strict):
    carrier: ShortText
    policy_number: Annotated[str, Field(min_length=1, max_length=60)]
    expires_on: date
    document_url: HttpUrl

    _https = field_validator("document_url")(_https_only)


# --- portfolio ---


class PortfolioIn(Strict):
    image_url: HttpUrl
    caption: Annotated[str, Field(max_length=280)] = ""
    trade_tag: str | None = None
    taken_on: date | None = None

    _https = field_validator("image_url")(_https_only)
    _trade = field_validator("trade_tag")(_check_trade)


class PortfolioCaption(Strict):
    caption: Annotated[str, Field(max_length=280)]


class PortfolioOrder(Strict):
    ids: list[str] = Field(max_length=500)


# --- quotes / inbox ---


class QuoteIn(Strict):
    name: ShortText
    phone: Phone | None = None
    email: EmailStr | None = None
    job_type: Annotated[str, Field(max_length=120)] | None = None
    message: Annotated[str, Field(min_length=1, max_length=2000)]
    # Honeypot: hidden on the form, so only bots fill it in.
    website: Annotated[str, Field(max_length=200)] = ""

    @model_validator(mode="after")
    def _needs_contact(self):
        if not self.phone and not self.email:
            raise ValueError("give a phone number or an email so the contractor can reply")
        return self


class QuoteStatus(str, Enum):
    """Follow-up status for an inquiry, whether it came through Trade Circle or was added by hand."""

    waiting = "waiting"
    followed_up = "followed_up"
    won = "won"
    closed = "closed"


# Statuses used before the follow-up tracker; converted on startup.
LEGACY_QUOTE_STATUS = {"new": "waiting", "contacted": "followed_up", "lost": "closed"}


class TrackerEntryIn(Strict):
    """An inquiry from a phone call, text or conversation, entered by hand."""

    name: ShortText
    phone: Phone | None = None
    email: EmailStr | None = None
    channel: Literal["phone", "text", "in_person", "other"] = "phone"
    job_type: Annotated[str, Field(max_length=120)] | None = None
    notes: Annotated[str, Field(max_length=4000)] = ""
    follow_up_on: date | None = None
    status: QuoteStatus = QuoteStatus.waiting


class QuoteUpdate(Strict):
    """Omitted fields stay as they are; null clears the follow-up date or contact details."""

    status: QuoteStatus | None = None
    notes: Annotated[str, Field(max_length=4000)] | None = None
    follow_up_on: date | None = None
    # Contact details can be edited on entries added by hand, not on requests a customer sent.
    name: ShortText | None = None
    phone: Phone | None = None
    email: EmailStr | None = None


# --- job sheet ---


class JobStatus(str, Enum):
    lead = "lead"
    scheduled = "scheduled"
    in_progress = "in_progress"
    done = "done"
    cancelled = "cancelled"
    # Set when another member accepts this job through a handoff.
    handed_off = "handed_off"


class JobIn(Strict):
    title: ShortText
    customer_name: Annotated[str, Field(max_length=120)] = ""
    customer_phone: Phone | None = None
    site_address: Annotated[str, Field(max_length=200)] = ""
    status: JobStatus = JobStatus.lead
    scheduled_on: date | None = None
    estimate_cents: Annotated[int, Field(ge=0, le=100_000_000)] | None = None
    notes: Annotated[str, Field(max_length=4000)] = ""
    # Set when the job was made from an inbox lead, so the lead stays linked.
    quote_id: Annotated[str, Field(max_length=64)] | None = None


# --- customer reviews ---


class ReviewResponseIn(Strict):
    """The contractor's public answer to a review. Sent again to edit it."""

    text: Annotated[str, Field(min_length=1, max_length=1000)]


class ReviewFlagIn(Strict):
    """Ask a moderator to look at a review. The review stays public meanwhile."""

    note: Annotated[str, Field(max_length=500)] = ""


class JobUpdate(Strict):
    """Omitted fields stay as they are; null clears a field that is optional."""

    title: ShortText | None = None
    customer_name: Annotated[str, Field(max_length=120)] | None = None
    customer_phone: Phone | None = None
    site_address: Annotated[str, Field(max_length=200)] | None = None
    status: JobStatus | None = None
    scheduled_on: date | None = None
    estimate_cents: Annotated[int, Field(ge=0, le=100_000_000)] | None = None
    notes: Annotated[str, Field(max_length=4000)] | None = None


# --- vacation and handoffs ---


class VacationIn(Strict):
    start_on: date
    end_on: date
    note: Annotated[str, Field(min_length=1, max_length=200)]


class HandoffIn(Strict):
    job_id: Annotated[str, Field(min_length=1, max_length=64)]
    recipient_slug: Annotated[str, Field(min_length=1, max_length=80)]
    start_on: date
    end_on: date | None = None
    note: Annotated[str, Field(max_length=500)] = ""


class HandoffReasonIn(Strict):
    reason: Annotated[str, Field(min_length=3, max_length=500)]


class CancelResponseIn(Strict):
    agree: bool
