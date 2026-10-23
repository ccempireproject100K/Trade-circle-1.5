import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .audit import AuditMiddleware
from .config import Settings, load_settings
from .https import HTTPSMiddleware
from .media import LocalMediaStore
from .ratelimit import RateLimiter
from .outbox import run_forever
from .routers import alerts, auth, billing, breakroom, calendar, community, connect, costing, estimates, handoffs, helper, jobs, marketplace, pages, payments, portfolio, profiles, quotes, rates, referrals, reviews, suppliers, team, timetrack


async def migrate(db) -> None:
    """One-off data changes, safe to run on every start."""
    from .models import LEGACY_QUOTE_STATUS

    for old, new in LEGACY_QUOTE_STATUS.items():
        await db.quotes.update_many({"status": old}, {"$set": {"status": new}})


async def ensure_indexes(db) -> None:
    await db.users.create_index("email", unique=True)
    await db.profiles.create_index("slug", unique=True)
    await db.profiles.create_index("owner_id", unique=True)
    await db.profiles.create_index([("trade", 1), ("city", 1)])
    await db.portfolio.create_index([("owner_id", 1), ("position", 1)])
    await db.quotes.create_index([("owner_id", 1), ("created_at", -1)])
    await db.quotes.create_index([("owner_id", 1), ("status", 1), ("follow_up_on", 1)])
    await db.jobs.create_index([("owner_id", 1), ("created_at", -1)])
    await db.outbox.create_index([("channel", 1), ("status", 1), ("next_attempt_at", 1)])
    await db.vacations.create_index([("owner_id", 1), ("start_on", 1)])
    await db.handoffs.create_index([("sender_id", 1), ("proposed_at", -1)])
    await db.handoffs.create_index([("recipient_id", 1), ("proposed_at", -1)])
    await db.handoffs.create_index("job_id")
    await db.posts.create_index([("status", 1), ("kind", 1), ("published_at", -1)])
    await db.posts.create_index([("author_id", 1), ("updated_at", -1)])
    await db.posts.create_index([("supplier_id", 1), ("published_at", -1)])
    await db.posts.create_index([("location.lat", 1), ("location.lon", 1)])
    await db.comments.create_index([("post_id", 1), ("created_at", 1)])
    await db.suppliers.create_index([("status", 1), ("name", 1)])
    await db.suppliers.create_index("website")
    await db.removal_requests.create_index([("status", 1), ("created_at", 1)])
    await db.reports.create_index([("status", 1), ("created_at", 1)])
    await db.rsvps.create_index("post_id")
    await db.message_requests.create_index([("to_id", 1), ("status", 1)])
    await db.message_requests.create_index([("from_id", 1), ("created_at", -1)])
    await db.conversations.create_index([("members", 1), ("last_message_at", -1)])
    await db.messages.create_index([("conversation_id", 1), ("created_at", 1)])
    await db.blocks.create_index("blocked_id")
    await db.notifications.create_index([("user_id", 1), ("created_at", -1)])
    await db.rate_submissions.create_index([("kind", 1), ("trade", 1), ("state", 1), ("submitted_on", 1)])
    await db.rate_submissions.create_index("contributor_id")
    await db.ai_usage.create_index([("feature", 1), ("day", 1)])
    await db.team_members.create_index([("business_id", 1), ("status", 1)])
    await db.team_members.create_index([("user_id", 1), ("status", 1)])
    await db.team_log.create_index([("business_id", 1), ("at", -1)])
    await db.break_room.create_index([("kind", 1), ("status", 1), ("expires_on", 1)])
    await db.usage_counts.create_index("day")
    await db.outside_estimates.create_index([("trade", 1), ("status", 1)])
    await db.estimate_corrections.create_index([("estimate_id", 1), ("status", 1)])
    await db.users.create_index("billing.customer_id", sparse=True)
    await db.payment_requests.create_index("token", unique=True)
    await db.payment_requests.create_index([("owner_id", 1), ("created_at", -1)])
    await db.payment_slices.create_index("request_id")
    await db.payment_slices.create_index("checkout_session")
    await db.payment_slices.create_index("payment_intent", sparse=True)
    await db.users.create_index("payments.account_id", sparse=True)
    await db.users.create_index("referred_by", sparse=True)
    await db.referral_earnings.create_index([("referrer_id", 1), ("month", 1)])
    await db.referral_earnings.create_index("charge", sparse=True)
    await db.referral_earnings.create_index("payment_intent", sparse=True)
    await db.referral_disputes.create_index([("referrer_id", 1), ("status", 1)])
    await db.time_entries.create_index("open_for", unique=True, sparse=True)
    await db.time_entries.create_index([("owner_id", 1), ("started_at", 1)])
    await db.time_entries.create_index([("owner_id", 1), ("job_id", 1)])
    await db.marketplace.create_index("token", unique=True)
    await db.marketplace.create_index([("trade", 1), ("status", 1), ("closes_on", 1)])
    await db.marketplace_bids.create_index([("contractor_id", 1), ("created_at", -1)])
    await db.marketplace_bids.create_index("request_id")
    # One review per lead, enforced by the database, not just the code.
    await db.reviews.create_index("lead_id", unique=True)
    await db.reviews.create_index([("owner_id", 1), ("created_at", -1)])
    await db.reviews.create_index([("status", 1), ("created_at", 1)])
    await db.audit_log.create_index([("user_id", 1), ("timestamp", -1)])


def create_app(settings: Settings | None = None, db=None, today=None, dashboard_dist: Path | None = None) -> FastAPI:
    settings = settings or load_settings()
    if db is None:
        from motor.motor_asyncio import AsyncIOMotorClient

        db = AsyncIOMotorClient(settings.mongo_url, tz_aware=True)[settings.db_name]

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await ensure_indexes(db)
        await migrate(db)
        worker = asyncio.create_task(run_forever(db, settings)) if settings.outbox_worker else None
        yield
        if worker is not None:
            worker.cancel()

    app = FastAPI(title="Trade Circle", lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db
    zone = ZoneInfo(settings.timezone)
    app.state.today = today or (lambda: datetime.now(zone).date())
    app.state.dashboard_dist = dashboard_dist or pages.DASHBOARD_DIST
    media_dir = Path(settings.media_dir) if settings.media_dir else Path(__file__).resolve().parents[2] / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    app.state.media = LocalMediaStore(media_dir)
    app.state.limiters = {
        "login": RateLimiter(settings.login_limit, settings.login_window_seconds),
        "quote": RateLimiter(settings.quote_limit, settings.quote_window_seconds),
        "quote_profile": RateLimiter(settings.quote_profile_limit, settings.quote_profile_window_seconds),
        # Community posting: generous for real members, tight enough to slow spam.
        "post": RateLimiter(30, 3600),
        "comment": RateLimiter(120, 3600),
        "message_request": RateLimiter(20, 86400),
    }

    # Added last runs first: HTTPS check, then audit, then the route.
    app.add_middleware(AuditMiddleware)
    app.add_middleware(HTTPSMiddleware)

    for module in (auth, profiles, portfolio, quotes, jobs, alerts, handoffs, community, suppliers, connect, rates, estimates, helper, team, breakroom, billing, payments, referrals, reviews, timetrack, costing, calendar, marketplace, pages):
        app.include_router(module.router)
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
    app.mount("/media", StaticFiles(directory=media_dir), name="media")

    @app.get("/health")
    async def health():
        return {"ok": True}

    return app
