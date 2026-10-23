"""Shared community posts.

One collection of posts serves every community feature, told apart by `kind`:
supply questions, supplier experiences and suggestions, project walkthroughs,
lessons from the job, equipment experiences and questions, and meetups. They
share comments, photos, trade tags, location, search and reporting, so each
feature only adds the few fields that are specific to it.
"""
from datetime import date
from enum import Enum
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .models import Strict, _check_trade

SUPPLY_CATEGORIES = (
    "lumber_building_materials",
    "electrical",
    "plumbing",
    "hvac",
    "roofing",
    "siding_exteriors",
    "paint_coatings",
    "flooring",
    "tools_equipment",
    "fasteners_hardware",
    "concrete_masonry",
    "landscape_irrigation",
    "safety_ppe",
    "other",
)
REVIEW_TOPICS = ("price", "quality", "availability", "delivery", "service", "returns")
REPORT_REASONS = ("spam", "harassment", "threat", "fabricated", "private_info", "other")


class Kind(str, Enum):
    supply_question = "supply_question"
    supplier_review = "supplier_review"
    supplier_suggestion = "supplier_suggestion"
    project = "project"
    lesson = "lesson"
    equipment = "equipment"
    equipment_question = "equipment_question"
    meetup = "meetup"
    opening = "opening"  # employment: a company hiring, never a customer project or lead
    spot = "spot"  # Break Room: a member's recommended place or deal


def Text(n: int):
    return Annotated[str, Field(max_length=n)]


# --- per-kind fields ---


class NoFields(Strict):
    pass


class SupplierReviewFields(Strict):
    experience: Literal["positive", "mixed", "negative"]
    topics: list[Literal["price", "quality", "availability", "delivery", "service", "returns"]] = Field(default_factory=list, max_length=6)


class SupplierSuggestionFields(Strict):
    suggested_name: Annotated[str, Field(min_length=1, max_length=120)]
    suggested_website: Text(200) = ""
    suggested_location: Text(120) = ""


class ProjectFields(Strict):
    """Answers to the walkthrough questions. All optional: members skip what they like."""

    job: Text(2000) = ""
    challenge: Text(2000) = ""
    handled: Text(2000) = ""
    learned: Text(2000) = ""
    step: Annotated[int, Field(ge=0, le=10)] = 0  # where the member left off, for draft recovery


class LessonFields(Strict):
    what_happened: Text(2000) = ""
    outcome: Text(2000) = ""
    resolution: Text(2000) = ""
    tip: Text(2000) = ""
    step: Annotated[int, Field(ge=0, le=10)] = 0


class EquipmentFields(Strict):
    product: Annotated[str, Field(min_length=1, max_length=120)]
    model: Text(120) = ""
    used_for: Text(1000) = ""
    durability: Text(2000) = ""
    problems: Text(2000) = ""
    repairs: Text(2000) = ""
    buy_again: Literal["yes", "no", "unsure", ""] = ""
    # Disclosure is required: members say whether they sell it or are sponsored.
    affiliation: Literal["none", "seller", "sponsor", "employee", "other"]
    affiliation_detail: Text(200) = ""

    @model_validator(mode="after")
    def _explain_affiliation(self):
        if self.affiliation != "none" and not self.affiliation_detail.strip():
            raise ValueError("describe your connection to this product (for example, which dealer you work for)")
        return self


class EquipmentQuestionFields(Strict):
    product: Text(120) = ""
    model: Text(120) = ""


class MeetupFields(Strict):
    starts_on: date
    starts_at: Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
    timezone: Annotated[str, Field(min_length=3, max_length=60)]
    general_location: Annotated[str, Field(min_length=1, max_length=160)]

    @field_validator("timezone")
    @classmethod
    def _real_zone(cls, value):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("choose a time zone such as America/Chicago")
        return value


class OpeningFields(Strict):
    role: Annotated[str, Field(min_length=1, max_length=120)]
    employment_type: Literal["full_time", "part_time", "seasonal", "apprenticeship", "temporary"]
    pay: Text(120) = ""
    requirements: Text(2000) = ""
    how_to_apply: Text(1000) = ""  # left empty, applicants message the poster
    apply_by: date | None = None
    filled: bool = False


class SpotFields(Strict):
    place: Annotated[str, Field(min_length=1, max_length=120)]
    suggestion: Literal["spot", "deal"]
    link: Annotated[str, Field(max_length=300, pattern=r"^(https?://\S+)?$")] = ""
    # Members say whether they own, work for or are paid by the place, so a recommendation can't pass as an ad.
    connection: Literal["none", "owner", "employee", "paid", "other"]
    connection_detail: Text(200) = ""

    @model_validator(mode="after")
    def _explain_connection(self):
        if self.connection != "none" and not self.connection_detail.strip():
            raise ValueError("describe your connection to this place")
        return self


FIELDS = {
    Kind.supply_question: NoFields,
    Kind.supplier_review: SupplierReviewFields,
    Kind.supplier_suggestion: SupplierSuggestionFields,
    Kind.project: ProjectFields,
    Kind.lesson: LessonFields,
    Kind.equipment: EquipmentFields,
    Kind.equipment_question: EquipmentQuestionFields,
    Kind.meetup: MeetupFields,
    Kind.opening: OpeningFields,
    Kind.spot: SpotFields,
}

# Kinds that only make sense with a place attached.
NEEDS_LOCATION = {Kind.meetup, Kind.opening, Kind.spot}

# Kinds a member can save as a draft and come back to.
DRAFTABLE = {Kind.project, Kind.lesson}


class PhotoRef(Strict):
    id: Annotated[str, Field(min_length=1, max_length=64)]
    group: Literal["", "before", "after"] = ""


def _clean_tags(tags):
    return None if tags is None else sorted({_check_trade(t) for t in tags})


def _check_category(value):
    if value is not None and value not in SUPPLY_CATEGORIES:
        raise ValueError(f"category must be one of: {', '.join(SUPPLY_CATEGORIES)}")
    return value


class PostIn(Strict):
    kind: Kind
    title: Text(140) = ""
    body: Text(10000) = ""
    trade_tags: list[str] = Field(default_factory=list, max_length=5)
    category: str | None = None
    location: Text(80) = ""  # ZIP or "City, ST"
    supplier_id: Text(64) | None = None
    photos: list[PhotoRef] = Field(default_factory=list, max_length=12)  # photos and video clips
    fields: dict = Field(default_factory=dict)
    featured: bool = False
    publish: bool = False

    _tags = field_validator("trade_tags")(_clean_tags)
    _category = field_validator("category")(_check_category)


class PostUpdate(Strict):
    title: Text(140) | None = None
    # Connect a post to a directory listing (or send null to disconnect).
    supplier_id: Text(64) | None = None
    body: Text(10000) | None = None
    trade_tags: list[str] | None = Field(default=None, max_length=5)
    category: str | None = None
    location: Text(80) | None = None
    photos: list[PhotoRef] | None = Field(default=None, max_length=12)
    fields: dict | None = None
    featured: bool | None = None

    _tags = field_validator("trade_tags")(_clean_tags)
    _category = field_validator("category")(_check_category)


class CommentIn(Strict):
    body: Annotated[str, Field(min_length=1, max_length=4000)]


class ReportIn(Strict):
    target_type: Literal["post", "comment", "supplier", "member", "message", "listing", "estimate", "lead"]
    target_id: Annotated[str, Field(min_length=1, max_length=64)]
    reason: Literal["spam", "harassment", "threat", "fabricated", "private_info", "other"]
    note: Text(1000) = ""


class ResolveIn(Strict):
    action: Literal["hide", "restore", "dismiss"]
    note: Text(1000) = ""


def validate_fields(kind: Kind, fields: dict) -> dict:
    return FIELDS[kind].model_validate(fields).model_dump(mode="json")


def needs_title(kind: Kind) -> bool:
    return kind not in DRAFTABLE



class RsvpIn(Strict):
    response: Literal["going", "maybe", "not_going"]


class MeetupUpdateIn(Strict):
    text: Annotated[str, Field(min_length=1, max_length=1000)]
