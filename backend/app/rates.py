"""Pay and billing-rate comparisons.

Members privately submit what they earn (employee wages) or charge (contractor
billing rates). Nobody can read another member's submission. Comparisons show
only aggregated, historical figures:

- each member counts once per group (a new submission replaces their old one),
- only submissions at least MIN_AGE_DAYS old are used, so nobody sees current prices,
- a group with fewer than MIN_CONTRIBUTORS members shows nothing at all,
- groups are statewide, never a city or ZIP, so sparse data isn't passed off as local.

The figures are self-reported and informational. They are not recommended or
coordinated rates. Publishing is off until the owner finishes the data-sharing
review (Settings.rate_comparisons); submissions are collected either way.
"""
import statistics
from datetime import date
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .models import Strict, TRADES

MIN_CONTRIBUTORS = 5
MIN_AGE_DAYS = 90
SOURCE = "Self-reported by Trade Circle members. Not verified."
DISCLAIMER = "For information only. These are not recommended or agreed rates; set your own prices from your own costs."

ROLES = ("helper", "apprentice", "journeyman", "foreman", "master", "estimator", "other")
EXPERIENCE = ("0-2", "3-5", "6-10", "11-20", "20+")
BENEFITS = ("health", "retirement", "paid_time_off", "vehicle", "tools", "training")

Money = Annotated[float, Field(ge=0, le=10000)]


class SubmissionIn(Strict):
    kind: Literal["wage", "billing"]
    trade: Literal[TRADES]  # type: ignore[valid-type]
    location: Annotated[str, Field(min_length=2, max_length=80)]  # ZIP or "City, ST"; only the state is kept
    # Employee wage
    role: Literal[ROLES] | None = None  # type: ignore[valid-type]
    experience: Literal[EXPERIENCE] | None = None  # type: ignore[valid-type]
    base_hourly: Money | None = None
    overtime_hourly: Money | None = None
    benefits: list[Literal[BENEFITS]] = Field(default_factory=list, max_length=len(BENEFITS))  # type: ignore[valid-type]
    # Contractor billing
    pricing: Literal["hourly", "project", "both"] | None = None
    labor_hourly: Money | None = None
    service_call_minimum: Money | None = None
    trip_charge: Money | None = None
    materials_markup_percent: Annotated[float, Field(ge=0, le=500)] | None = None

    @model_validator(mode="after")
    def _complete(self):
        if self.kind == "wage":
            if self.base_hourly is None or self.role is None:
                raise ValueError("add your role and base hourly pay")
            if any(v is not None for v in (self.pricing, self.labor_hourly, self.service_call_minimum, self.trip_charge, self.materials_markup_percent)):
                raise ValueError("billing details belong in a billing-rate submission")
        else:
            if self.pricing is None:
                raise ValueError("say whether you bill hourly, by the project or both")
            if self.pricing != "project" and self.labor_hourly is None:
                raise ValueError("add your hourly labor rate")
            if any(v is not None for v in (self.role, self.experience, self.base_hourly, self.overtime_hourly)) or self.benefits:
                raise ValueError("wage details belong in a wage submission")
        return self


WAGE_METRICS = ("base_hourly", "overtime_hourly")
BILLING_METRICS = ("labor_hourly", "service_call_minimum", "trip_charge", "materials_markup_percent")


def _range(values: list[float]) -> dict:
    low, mid, high = statistics.quantiles(values, n=4, method="inclusive")
    return {"low": round(low), "median": round(mid), "high": round(high), "sample_size": len(values)}


def aggregate(rows: list[dict], kind: str) -> dict:
    """Summarize one group's submissions. Caller has already applied the age and grouping rules."""
    if len(rows) < MIN_CONTRIBUTORS:
        return {"insufficient_data": True, "min_contributors": MIN_CONTRIBUTORS}
    metrics = {}
    for key in WAGE_METRICS if kind == "wage" else BILLING_METRICS:
        values = [r[key] for r in rows if r.get(key) is not None]
        # Each figure needs enough answers of its own; a figure few people gave stays hidden.
        if len(values) >= MIN_CONTRIBUTORS:
            metrics[key] = _range(values)
    out = {
        "insufficient_data": False,
        "sample_size": len(rows),
        "metrics": metrics,
        # Months only: exact dates would help pick out one member's submission.
        "oldest_month": min(r["submitted_on"] for r in rows)[:7],
        "newest_month": max(r["submitted_on"] for r in rows)[:7],
        "source": SOURCE,
        "disclaimer": DISCLAIMER,
    }
    if kind == "wage":
        out["benefits"] = {b: round(100 * sum(b in r.get("benefits", []) for r in rows) / len(rows)) for b in BENEFITS}
    else:
        out["pricing"] = {p: round(100 * sum(r.get("pricing") in (p, "both") for r in rows) / len(rows)) for p in ("hourly", "project")}
    return out


def cutoff(today: date) -> str:
    from datetime import timedelta

    return (today - timedelta(days=MIN_AGE_DAYS)).isoformat()
