"""Payment requests for Full-plan contractors, and the public payment page. Rules are in app/payments.py."""
import logging
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import EmailStr, Field, model_validator

from .. import billing, payments, stripe_api
from ..deps import get_db, now
from ..models import Strict
from ..profiles import DEFAULT_BRAND_COLOR, text_color_on
from ..ratelimit import client_ip
from ..security import current_user
from ..tiers import allows, require
from .billing import _receive
from .pages import templates

router = APIRouter(tags=["payments"])
log = logging.getLogger("trade_circle.payments")

# The payment page posts to us and is then sent on to Stripe's checkout.
PAY_CSP = (
    "default-src 'self'; img-src 'self' https: data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self' https://checkout.stripe.com"
)
MIN_PAYMENT_CENTS = 100


class RequestIn(Strict):
    customer_name: Annotated[str, Field(min_length=1, max_length=120)]
    customer_email: EmailStr | None = None
    description: Annotated[str, Field(min_length=2, max_length=140)]
    amount_cents: Annotated[int, Field(ge=MIN_PAYMENT_CENTS, le=10_000_000)]
    note: Annotated[str, Field(max_length=140)] = ""  # one line shown on the payment page
    job_id: Annotated[str, Field(max_length=64)] | None = None
    allow_partial: bool = False
    min_partial_cents: Annotated[int, Field(ge=MIN_PAYMENT_CENTS)] | None = None
    card: bool = True
    bank: bool = True
    offer_save_card: bool = False  # let the customer keep their card on file with this contractor

    @model_validator(mode="after")
    def _check(self):
        if not (self.card or self.bank):
            raise ValueError("allow card, bank transfer or both")
        if self.min_partial_cents and self.min_partial_cents > self.amount_cents:
            raise ValueError("the smallest part can't be more than the total")
        return self


def _stripe(request: Request):
    return billing.stripe_client(request.app)


def _ready(request: Request) -> bool:
    s = request.app.state.settings
    return bool(s.stripe_secret_key and s.stripe_connect_webhook_secret)


def _account(user: dict) -> dict:
    return user.get("payments") or {}


@router.get("/api/payments/account")
async def account(request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    p = _account(user)
    if p.get("account_id") and not p.get("charges_enabled") and _ready(request):
        # Coming back from onboarding: ask Stripe where things stand.
        try:
            acct = await _stripe(request).request("GET", f"/accounts/{p['account_id']}")
            p = {**p, "charges_enabled": bool(acct.get("charges_enabled")), "details_submitted": bool(acct.get("details_submitted"))}
            await db.users.update_one({"_id": user["_id"]}, {"$set": {"payments.charges_enabled": p["charges_enabled"], "payments.details_submitted": p["details_submitted"]}})
        except stripe_api.StripeError:
            pass
    return {
        "ready": _ready(request),
        "plan_allows": allows(user, "customer_payments"),
        "connected": bool(p.get("account_id")),
        "charges_enabled": bool(p.get("charges_enabled")),
        "details_submitted": bool(p.get("details_submitted")),
    }


@router.post("/api/payments/connect")
async def connect(request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    """Send the contractor to Stripe's own onboarding to connect (or finish connecting) their account."""
    require(user, "customer_payments")
    if not _ready(request):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Customer payments aren't open yet.")
    stripe, base = _stripe(request), request.app.state.settings.public_url
    try:
        account_id = _account(user).get("account_id")
        if not account_id:
            acct = await stripe.request("POST", "/accounts", {"type": "standard", "email": user["email"], "metadata": {"user_id": user["_id"]}}, idempotency_key=f"acct-{user['_id']}")
            account_id = acct["id"]
            await db.users.update_one({"_id": user["_id"]}, {"$set": {"payments": {"account_id": account_id, "charges_enabled": False, "details_submitted": False, "connected_at": now()}}})
        link = await stripe.request("POST", "/account_links", {"account": account_id, "type": "account_onboarding", "refresh_url": f"{base}/app/payments?connect=retry", "return_url": f"{base}/app/payments?connect=done"})
    except stripe_api.StripeError as exc:
        log.warning("connect failed for %s: %s", user["_id"], exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "We couldn't reach Stripe. Please try again.")
    return {"url": link["url"]}


async def _request_view(db, r: dict, public_url: str) -> dict:
    b = await payments.balance(db, r)
    slices = await db.payment_slices.find({"request_id": r["_id"], "status": {"$in": ["succeeded", "processing", "failed"]}}).sort("created_at", 1).to_list(200)
    return {
        "id": r["_id"],
        **{k: r.get(k) for k in ("customer_name", "customer_email", "description", "amount_cents", "note", "job_id", "allow_partial", "min_partial_cents", "card", "bank", "offer_save_card", "status", "created_at")},
        **b,
        "link": f"{public_url}/pay/{r['token']}",
        "payments": [{"amount_cents": s["amount_cents"], "method": s["method"], "status": s["status"], "refunded_cents": s.get("refunded_cents", 0), "at": s.get("updated_at") or s["created_at"]} for s in slices],
    }


@router.post("/api/payments/requests", status_code=status.HTTP_201_CREATED)
async def create_request(body: RequestIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    require(user, "customer_payments")
    if not _account(user).get("charges_enabled"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Connect your Stripe account first, so payments go to you.")
    if body.job_id and not await db.jobs.find_one({"_id": body.job_id, "owner_id": user["_id"]}, {"_id": 1}):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    doc = {
        "_id": uuid.uuid4().hex, "owner_id": user["_id"], "token": payments.new_token(),
        **body.model_dump(mode="json"), "customer_email": (body.customer_email or "").lower() or None,
        "status": "open", "created_at": now(), "updated_at": now(),
    }
    await db.payment_requests.insert_one(doc)
    request.state.audit_record = doc["_id"]
    return await _request_view(db, doc, request.app.state.settings.public_url)


@router.get("/api/payments/requests")
async def list_requests(request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    found = await db.payment_requests.find({"owner_id": user["_id"]}).sort("created_at", -1).limit(200).to_list(200)
    return [await _request_view(db, r, request.app.state.settings.public_url) for r in found]


@router.post("/api/payments/requests/{request_id}/cancel")
async def cancel_request(request_id: str, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    """Stop taking payments on a request. Anything already paid stays paid; refunds are made in Stripe."""
    r = await db.payment_requests.find_one_and_update({"_id": request_id, "owner_id": user["_id"], "status": {"$in": list(payments.OPEN)}}, {"$set": {"status": "cancelled", "updated_at": now()}}, return_document=True)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No open request like that")
    return await _request_view(db, r, request.app.state.settings.public_url)


# --- the public payment page ---


async def _page_context(db, token: str) -> tuple[dict, dict, dict] | None:
    r = await db.payment_requests.find_one({"token": token})
    if r is None:
        return None
    profile = await db.profiles.find_one({"owner_id": r["owner_id"]}) or {}
    owner = await db.users.find_one({"_id": r["owner_id"]}) or {}
    return r, profile, owner


def _render(request: Request, ctx: dict, status_code: int = 200) -> HTMLResponse:
    response = templates.TemplateResponse(request, "pay.html", ctx, status_code=status_code)
    response.headers["Content-Security-Policy"] = PAY_CSP
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"  # the link itself is the key to this page
    return response


@router.get("/pay/{token}", response_class=HTMLResponse, include_in_schema=False)
async def pay_page(token: str, request: Request, db=Depends(get_db), paid: str = "", error: str = ""):
    found = await _page_context(db, token)
    if found is None:
        return _render(request, {"missing": True}, 404)
    r, profile, owner = found
    brand = profile.get("brand_color") or DEFAULT_BRAND_COLOR
    b = await payments.balance(db, r)
    usable = r["status"] in payments.OPEN and (owner.get("payments") or {}).get("charges_enabled") and owner.get("tier") == "full" and _ready(request)
    return _render(request, {
        "r": r, "b": b, "business": profile.get("business_name", "Your contractor"), "slug": profile.get("slug"),
        "brand": brand, "brand_text": text_color_on(brand), "money": payments.money, "usable": usable,
        "paid": paid == "1", "error": error, "min_cents": min(b["due_cents"], r.get("min_partial_cents") or MIN_PAYMENT_CENTS),
    })


@router.post("/pay/{token}", include_in_schema=False)
async def pay(token: str, request: Request, db=Depends(get_db), method: str = Form("card"), amount: str = Form(""), save_card: str = Form("")):
    """Start one payment (one slice) on Stripe's checkout page, on the contractor's own account."""
    request.app.state.limiters["quote"].check(f"pay:{client_ip(request)}")
    found = await _page_context(db, token)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    r, profile, owner = found
    back = f"/pay/{token}"
    acct = (owner.get("payments") or {}).get("account_id")
    if r["status"] not in payments.OPEN or not acct or owner.get("tier") != "full" or not _ready(request):
        return RedirectResponse(f"{back}?error=closed", status.HTTP_303_SEE_OTHER)
    b = await payments.balance(db, r)
    try:
        cents = round(float(amount.replace("$", "").replace(",", "")) * 100) if (amount and r.get("allow_partial")) else b["due_cents"]
    except ValueError:
        return RedirectResponse(f"{back}?error=amount", status.HTTP_303_SEE_OTHER)
    smallest = min(b["due_cents"], r.get("min_partial_cents") or MIN_PAYMENT_CENTS)
    if cents < smallest or cents > b["due_cents"] or b["due_cents"] == 0:
        return RedirectResponse(f"{back}?error=amount", status.HTTP_303_SEE_OTHER)
    if method not in ("card", "bank") or (method == "card" and not r["card"]) or (method == "bank" and not r["bank"]):
        return RedirectResponse(f"{back}?error=method", status.HTTP_303_SEE_OTHER)
    slice_id = uuid.uuid4().hex
    base = request.app.state.settings.public_url
    params: dict = {
        "mode": "payment",
        "payment_method_types": ["card"] if method == "card" else ["us_bank_account"],
        "line_items": [{"quantity": 1, "price_data": {"currency": "usd", "unit_amount": cents, "product_data": {"name": r["description"][:120]}}}],
        "success_url": f"{base}/pay/{token}?paid=1",
        "cancel_url": f"{base}/pay/{token}",
        "client_reference_id": slice_id,
        "metadata": {"payment_request": r["_id"], "slice": slice_id},
        "payment_intent_data": {"description": f"{r['description']} ({profile.get('business_name', '')})"[:200], "metadata": {"payment_request": r["_id"], "slice": slice_id}},
    }
    if r.get("customer_email"):
        saved = await db.payment_customers.find_one({"_id": f"{r['owner_id']}:{r['customer_email']}"})
        if saved:
            params["customer"] = saved["stripe_customer"]  # their card on file with this contractor is offered
        else:
            params["customer_email"] = r["customer_email"]
            params["customer_creation"] = "always"
    if method == "card" and r.get("offer_save_card") and save_card == "on":
        params["payment_intent_data"]["setup_future_usage"] = "off_session"
        if "customer" not in params:
            params["customer_creation"] = "always"
    # Close any earlier unfinished checkout for this request, so two open tabs can't both be paid.
    async for old in db.payment_slices.find({"request_id": r["_id"], "status": "pending"}):
        try:
            await _stripe(request).request("POST", f"/checkout/sessions/{old['checkout_session']}/expire", account=acct)
        except stripe_api.StripeError:
            pass  # already completed or expired; its webhook will say which
        else:
            await db.payment_slices.update_one({"_id": old["_id"], "status": "pending"}, {"$set": {"status": "expired", "updated_at": now()}})
    try:
        session = await _stripe(request).request("POST", "/checkout/sessions", params, account=acct, idempotency_key=f"slice-{slice_id}")
    except stripe_api.StripeError as exc:
        log.warning("checkout for request %s failed: %s", r["_id"], exc)
        return RedirectResponse(f"{back}?error=stripe", status.HTTP_303_SEE_OTHER)
    await db.payment_slices.insert_one({
        "_id": slice_id, "request_id": r["_id"], "owner_id": r["owner_id"], "account_id": acct, "amount_cents": cents,
        "method": method, "checkout_session": session["id"], "status": "pending", "created_at": now(),
    })
    return RedirectResponse(session["url"], status.HTTP_303_SEE_OTHER)


@router.post("/api/stripe/connect-webhook", include_in_schema=False)
async def connect_webhook(request: Request):
    return await _receive(request, request.app.state.settings.stripe_connect_webhook_secret, [payments.handle_connect_event])
