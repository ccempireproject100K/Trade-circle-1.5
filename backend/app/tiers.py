"""Plans and what each includes. Every feature gate reads this file, so pricing changes touch one place."""
from fastapi import HTTPException, status

TIER_ORDER = {"free": 0, "starter": 1, "full": 2}

PLANS = {
    "free": {"name": "Free", "price_cents": 0},
    "starter": {"name": "Starter", "price_cents": 300},
    "full": {"name": "Full", "price_cents": 900},
}

# Feature key -> (lowest plan that includes it, how it's described, built in Trade Circle?).
# Features that aren't built are listed so plan descriptions stay honest; they're never sold as working.
FEATURES = {
    "lead_alerts": ("starter", "Instant text and email alerts for new leads", True),
    "daily_summary": ("starter", "Daily email summary and afternoon follow-up text", True),
    "time_tracking": ("starter", "Time tracking on jobs", True),
    "custom_domain": ("starter", "Your own domain for your page (CNAME)", True),
    "google_business_profile": ("starter", "Google Business Profile sync", False),
    "youtube_autopost": ("starter", "YouTube auto-posting", False),
    "customer_payments": ("full", "Take card and bank payments from customers (Stripe)", True),
    "marketplace_unlimited": ("full", "Unlimited lead marketplace bids", True),
    "profile_report": ("full", "Monthly profile performance report", True),
    "voice_onboarding": ("full", "Voice onboarding", True),
    "priority_support": ("full", "Priority support", True),
    "empire_invoicing": ("full", "Invoicing through Empire", False),
    "crew_sharing": ("full", "Crew sharing", False),
}
# Everyone gets these, whatever their plan.
FREE_FEATURES = [
    "Business page, full profile and quote form",
    "Customer reviews on your page",
    "Photo portfolio and video clips",
    "Job sheet, follow-ups, calendar and job costing",
    "Community, Supplies, Hiring, Break Room and handoffs",
    "Pay & rates and the cost calculator",
    "3 lead marketplace bids a month",
]

# New-lead alerts (email and text). Free-plan contractors log in to see leads.
ALERTS_TIER = FEATURES["lead_alerts"][0]
MARKETPLACE_FREE_BIDS = 3


def has_tier(user: dict, tier: str) -> bool:
    return TIER_ORDER.get(user.get("tier", "free"), 0) >= TIER_ORDER[tier]


def require_tier(user: dict, tier: str, feature: str) -> None:
    if not has_tier(user, tier):
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, f"{feature} needs the {PLANS[tier]['name']} plan or higher")


def allows(user: dict, feature: str) -> bool:
    return has_tier(user, FEATURES[feature][0])


def require(user: dict, feature: str) -> None:
    tier, label, _ = FEATURES[feature]
    require_tier(user, tier, label)


def catalog() -> list[dict]:
    """Each plan with what it adds, for the plan screen."""
    out = []
    for key, plan in PLANS.items():
        adds = [{"key": f, "label": label, "built": built} for f, (tier, label, built) in FEATURES.items() if tier == key]
        out.append({"key": key, **plan, "adds": adds, "includes": FREE_FEATURES if key == "free" else []})
    return out
