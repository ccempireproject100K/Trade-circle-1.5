import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    jwt_secret: str
    mongo_url: str = "mongodb://localhost:27017"
    db_name: str = "trade_circle"
    token_ttl_minutes: int = 12 * 60
    # Redirect plain HTTP to HTTPS and send HSTS. Off only for local dev.
    enforce_https: bool = True
    # Trust X-Forwarded-For / X-Forwarded-Proto. Only enable behind our own proxy.
    trust_proxy: bool = False
    login_limit: int = 5
    login_window_seconds: int = 300
    quote_limit: int = 5
    quote_window_seconds: int = 600
    quote_profile_limit: int = 30
    quote_profile_window_seconds: int = 3600
    recert_banner_days: int = 3
    # Where uploaded photos are stored. Defaults to media/ next to backend/.
    media_dir: str = ""
    # Local calendar for "today" and for the handoff week (Monday to Sunday).
    timezone: str = "America/Chicago"
    # Footer link to the Academy; omitted from pages until set.
    academy_url: str | None = None
    # The operating entity named on the legal pages (/privacy, /terms). The
    # contact email and mailing address render on those pages only when set.
    legal_entity: str = "Mind At Ease Solutions"
    legal_email: str = ""
    legal_address: str = ""
    # Public address of this site, used for links in text messages.
    public_url: str = "https://tradecircle.mindateasesolutions.com"
    # Twilio. Same variable names as the Mind At Ease site, so both can share one account.
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_messaging_sid: str = ""
    twilio_from_number: str = ""
    # Resend. Same variable names as the Mind At Ease site, so both can share one account.
    resend_api_key: str = ""
    resend_from_email: str = ""
    email_from_name: str = "Trade Circle"
    email_reply_to: str = ""
    # Deliver queued alerts from inside the app process.
    outbox_worker: bool = False
    # Publish aggregated pay and billing-rate comparisons. Off until the data-sharing review is done.
    rate_comparisons: bool = False
    # AI features. Nothing is sent to a provider until the key, model, both prices (USD per
    # million tokens) and a monthly budget (USD) are all set. Allowances are per member.
    ai_api_key: str = ""
    ai_model: str = ""
    ai_input_price: float = 0.0
    ai_output_price: float = 0.0
    ai_monthly_budget: float = 0.0
    ai_daily_limit: int = 3
    ai_monthly_limit: int = 10
    ai_max_output_tokens: int = 2000
    # Stripe. Subscriptions (Starter and Full monthly prices) and contractors' customer payments (Connect).
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_connect_webhook_secret: str = ""
    stripe_price_starter: str = ""
    stripe_price_full: str = ""
    # Photo part identification has its own allowance and budget, off (0) until approved.
    parts_monthly_budget: float = 0.0
    parts_daily_limit: int = 0
    parts_monthly_limit: int = 0
    # Encrypts stored secrets (today: members' YouTube refresh tokens) at rest.
    # Falls back to the JWT secret when unset; changing it means connected members reconnect.
    encryption_key: str = ""
    # YouTube auto-posting (a YouTube integration, not a partnership). Nothing is
    # posted until the site's Google OAuth client is configured; members then
    # connect their own channels. One upload costs 1,600 of the project's 10,000
    # daily quota units, so the default cap keeps the whole site at 6 uploads a day.
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_redirect_uri: str = ""
    youtube_daily_uploads: int = 6

    @property
    def youtube_ready(self) -> bool:
        return bool(self.youtube_client_id and self.youtube_client_secret and self.youtube_redirect_uri)

    @property
    def email_ready(self) -> bool:
        return bool(self.resend_api_key and self.resend_from_email)

    @property
    def twilio_ready(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and (self.twilio_messaging_sid or self.twilio_from_number))


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    secret = os.environ.get("TC_JWT_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("TC_JWT_SECRET must be set to at least 32 characters")
    return Settings(
        jwt_secret=secret,
        mongo_url=os.environ.get("TC_MONGO_URL", Settings.mongo_url),
        db_name=os.environ.get("TC_DB_NAME", Settings.db_name),
        enforce_https=_flag("TC_ENFORCE_HTTPS", True),
        trust_proxy=_flag("TC_TRUST_PROXY", False),
        academy_url=os.environ.get("TC_ACADEMY_URL") or None,
        legal_entity=os.environ.get("TC_LEGAL_ENTITY") or Settings.legal_entity,
        legal_email=os.environ.get("TC_LEGAL_EMAIL", ""),
        legal_address=os.environ.get("TC_LEGAL_ADDRESS", ""),
        public_url=os.environ.get("TC_PUBLIC_URL", Settings.public_url).rstrip("/"),
        twilio_account_sid=os.environ.get("TWILIO_ACCOUNT_SID", ""),
        twilio_auth_token=os.environ.get("TWILIO_AUTH_TOKEN", ""),
        twilio_messaging_sid=os.environ.get("TWILIO_MESSAGING_SID", ""),
        twilio_from_number=os.environ.get("TWILIO_FROM_NUMBER", ""),
        resend_api_key=os.environ.get("RESEND_API_KEY", ""),
        resend_from_email=os.environ.get("RESEND_FROM_EMAIL", ""),
        email_from_name=os.environ.get("EMAIL_FROM_NAME", Settings.email_from_name),
        email_reply_to=os.environ.get("EMAIL_REPLY_TO", ""),
        outbox_worker=_flag("TC_OUTBOX_WORKER", True),
        rate_comparisons=_flag("TC_RATE_COMPARISONS", False),
        ai_api_key=os.environ.get("TC_AI_API_KEY", ""),
        ai_model=os.environ.get("TC_AI_MODEL", ""),
        ai_input_price=float(os.environ.get("TC_AI_INPUT_PRICE", "0") or 0),
        ai_output_price=float(os.environ.get("TC_AI_OUTPUT_PRICE", "0") or 0),
        ai_monthly_budget=float(os.environ.get("TC_AI_MONTHLY_BUDGET", "0") or 0),
        ai_daily_limit=int(os.environ.get("TC_AI_DAILY_LIMIT", "3")),
        ai_monthly_limit=int(os.environ.get("TC_AI_MONTHLY_LIMIT", "10")),
        ai_max_output_tokens=int(os.environ.get("TC_AI_MAX_OUTPUT_TOKENS", "2000")),
        stripe_secret_key=os.environ.get("STRIPE_SECRET_KEY", ""),
        stripe_webhook_secret=os.environ.get("STRIPE_WEBHOOK_SECRET", ""),
        stripe_connect_webhook_secret=os.environ.get("STRIPE_CONNECT_WEBHOOK_SECRET", ""),
        stripe_price_starter=os.environ.get("STRIPE_PRICE_STARTER", ""),
        stripe_price_full=os.environ.get("STRIPE_PRICE_FULL", ""),
        encryption_key=os.environ.get("TC_ENCRYPTION_KEY", ""),
        youtube_client_id=os.environ.get("TC_YOUTUBE_CLIENT_ID", ""),
        youtube_client_secret=os.environ.get("TC_YOUTUBE_CLIENT_SECRET", ""),
        youtube_redirect_uri=os.environ.get("TC_YOUTUBE_REDIRECT_URI", ""),
        youtube_daily_uploads=int(os.environ.get("TC_YOUTUBE_DAILY_UPLOADS", "6") or 6),
        parts_monthly_budget=float(os.environ.get("TC_PARTS_MONTHLY_BUDGET", "0") or 0),
        parts_daily_limit=int(os.environ.get("TC_PARTS_DAILY_LIMIT", "0")),
        parts_monthly_limit=int(os.environ.get("TC_PARTS_MONTHLY_LIMIT", "0")),
        timezone=os.environ.get("TC_TIMEZONE", Settings.timezone),
        media_dir=os.environ.get("TC_MEDIA_DIR", ""),
    )
