"""Job costing (estimate versus actual) and reusable templates, including seasonal quote templates.

Job costing compares what a job was expected to cost with what it did cost,
against the price charged. Actual labor includes time tracked on the job at the
member's labor cost per hour. Margin is profit as a share of the price; markup
is profit as a share of the cost.

Quote templates hold a standard set of line items, with optional seasonal
adjustments (for example +15% in June to August for AC work). Pricing a
template for a date applies the season that date falls in.
"""
import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import Field, field_validator

from ..deps import get_db, now
from ..models import Strict
from ..team import acting_for
from .timetrack import job_minutes

router = APIRouter(prefix="/api", tags=["costing"])

Cents = Annotated[int, Field(ge=0, le=100_000_000)]
Text = Annotated[str, Field(max_length=140)]


class CostLine(Strict):
    kind: Literal["labor", "materials", "equipment", "subcontract", "permits", "other"]
    description: Text = ""
    quantity: Annotated[float, Field(ge=0, le=100_000)] = 1
    unit_cost_cents: Cents = 0


class CostingIn(Strict):
    price_cents: Cents | None = None  # what the customer pays; defaults to the job's estimate
    labor_cost_per_hour_cents: Cents = 0  # what an hour of tracked time costs you, wages and burden
    overhead_percent: Annotated[float, Field(ge=0, le=200)] = 0  # added to direct costs
    estimate: list[CostLine] = Field(default_factory=list, max_length=100)
    actual: list[CostLine] = Field(default_factory=list, max_length=100)


class TemplateIn(Strict):
    name: Annotated[str, Field(min_length=2, max_length=80)]
    lines: list[CostLine] = Field(default_factory=list, max_length=100)


class Season(Strict):
    label: Annotated[str, Field(min_length=1, max_length=60)]
    months: list[Annotated[int, Field(ge=1, le=12)]] = Field(min_length=1, max_length=12)
    adjust_percent: Annotated[float, Field(ge=-50, le=100)]


class QuoteItem(Strict):
    description: Annotated[str, Field(min_length=1, max_length=140)]
    price_cents: Cents


class QuoteTemplateIn(Strict):
    name: Annotated[str, Field(min_length=2, max_length=80)]
    items: list[QuoteItem] = Field(min_length=1, max_length=50)
    seasons: list[Season] = Field(default_factory=list, max_length=12)

    @field_validator("seasons")
    @classmethod
    def _no_overlap(cls, seasons):
        seen = set()
        for s in seasons:
            if seen & set(s.months):
                raise ValueError("a month can only be in one season")
            seen |= set(s.months)
        return seasons


def _sum(lines: list[dict]) -> int:
    return round(sum(l["quantity"] * l["unit_cost_cents"] for l in lines))


def _by_kind(lines: list[dict]) -> dict:
    out: dict = {}
    for l in lines:
        out[l["kind"]] = out.get(l["kind"], 0) + round(l["quantity"] * l["unit_cost_cents"])
    return out


def summarize(costing: dict, job: dict, tracked_minutes: int) -> dict:
    price = costing.get("price_cents") if costing.get("price_cents") is not None else (job.get("estimate_cents") or 0)
    overhead = costing.get("overhead_percent", 0) / 100
    tracked_labor = round(tracked_minutes / 60 * costing.get("labor_cost_per_hour_cents", 0))

    def totals(lines: list[dict], extra_labor: int = 0) -> dict:
        direct = _sum(lines) + extra_labor
        cost = round(direct * (1 + overhead))
        profit = price - cost
        return {
            "direct_cents": direct,
            "overhead_cents": cost - direct,
            "cost_cents": cost,
            "profit_cents": profit,
            "margin_percent": round(profit / price * 100, 1) if price else None,
            "markup_percent": round(profit / cost * 100, 1) if cost else None,
        }

    est, act = costing.get("estimate", []), costing.get("actual", [])
    actual_kinds = _by_kind(act)
    if tracked_labor:
        actual_kinds["labor"] = actual_kinds.get("labor", 0) + tracked_labor
    est_kinds = _by_kind(est)
    return {
        "price_cents": price,
        "tracked_hours": round(tracked_minutes / 60, 2),
        "tracked_labor_cents": tracked_labor,
        "estimate": totals(est),
        "actual": totals(act, tracked_labor),
        # Positive means it cost more than expected.
        "variance": {k: actual_kinds.get(k, 0) - est_kinds.get(k, 0) for k in sorted(set(est_kinds) | set(actual_kinds))},
    }


async def _job(db, owner_id: str, job_id: str) -> dict:
    job = await db.jobs.find_one({"_id": job_id, "owner_id": owner_id})
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return job


async def _costing_view(db, job: dict) -> dict:
    costing = job.get("costing") or {"price_cents": None, "labor_cost_per_hour_cents": 0, "overhead_percent": 0, "estimate": [], "actual": []}
    return {**costing, "job": {"id": job["_id"], "title": job["title"], "estimate_cents": job.get("estimate_cents")}, "summary": summarize(costing, job, await job_minutes(db, job["owner_id"], job["_id"]))}


@router.get("/jobs/{job_id}/costing")
async def get_costing(job_id: str, user: dict = Depends(acting_for("jobs")), db=Depends(get_db)):
    return await _costing_view(db, await _job(db, user["_id"], job_id))


@router.put("/jobs/{job_id}/costing")
async def put_costing(job_id: str, body: CostingIn, user: dict = Depends(acting_for("jobs")), db=Depends(get_db)):
    await _job(db, user["_id"], job_id)
    await db.jobs.update_one({"_id": job_id, "owner_id": user["_id"]}, {"$set": {"costing": body.model_dump(), "costing_updated_at": now()}})
    return await _costing_view(db, await _job(db, user["_id"], job_id))


# --- costing templates ---


def _tview(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k not in ("_id", "owner_id")} | {"id": doc["_id"]}


@router.get("/costing/templates")
async def list_templates(user: dict = Depends(acting_for("jobs")), db=Depends(get_db)):
    return [_tview(t) async for t in db.costing_templates.find({"owner_id": user["_id"]}).sort("name", 1)]


@router.post("/costing/templates", status_code=status.HTTP_201_CREATED)
async def add_template(body: TemplateIn, user: dict = Depends(acting_for("jobs")), db=Depends(get_db)):
    doc = {"_id": uuid.uuid4().hex, "owner_id": user["_id"], **body.model_dump(), "created_at": now()}
    await db.costing_templates.insert_one(doc)
    return _tview(doc)


@router.delete("/costing/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(template_id: str, user: dict = Depends(acting_for("jobs")), db=Depends(get_db)):
    if not (await db.costing_templates.delete_one({"_id": template_id, "owner_id": user["_id"]})).deleted_count:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- seasonal quote templates ---


def price_quote(template: dict, on: date) -> dict:
    subtotal = sum(i["price_cents"] for i in template["items"])
    season = next((s for s in template.get("seasons", []) if on.month in s["months"]), None)
    pct = season["adjust_percent"] if season else 0
    items = [{**i, "adjusted_cents": round(i["price_cents"] * (1 + pct / 100))} for i in template["items"]]
    return {"on": on.isoformat(), "season": season, "items": items, "subtotal_cents": subtotal, "total_cents": sum(i["adjusted_cents"] for i in items)}


@router.get("/quote-templates")
async def list_quote_templates(user: dict = Depends(acting_for("jobs")), db=Depends(get_db)):
    return [_tview(t) async for t in db.quote_templates.find({"owner_id": user["_id"]}).sort("name", 1)]


@router.post("/quote-templates", status_code=status.HTTP_201_CREATED)
async def add_quote_template(body: QuoteTemplateIn, user: dict = Depends(acting_for("jobs")), db=Depends(get_db)):
    doc = {"_id": uuid.uuid4().hex, "owner_id": user["_id"], **body.model_dump(), "created_at": now()}
    await db.quote_templates.insert_one(doc)
    return _tview(doc)


@router.put("/quote-templates/{template_id}")
async def update_quote_template(template_id: str, body: QuoteTemplateIn, user: dict = Depends(acting_for("jobs")), db=Depends(get_db)):
    doc = await db.quote_templates.find_one_and_update({"_id": template_id, "owner_id": user["_id"]}, {"$set": {**body.model_dump(), "updated_at": now()}}, return_document=True)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    return _tview(doc)


@router.delete("/quote-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quote_template(template_id: str, user: dict = Depends(acting_for("jobs")), db=Depends(get_db)):
    if not (await db.quote_templates.delete_one({"_id": template_id, "owner_id": user["_id"]})).deleted_count:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/quote-templates/{template_id}/price")
async def price(template_id: str, on: date, user: dict = Depends(acting_for("jobs")), db=Depends(get_db)):
    doc = await db.quote_templates.find_one({"_id": template_id, "owner_id": user["_id"]})
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    return price_quote(doc, on)
