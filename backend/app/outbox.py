"""Delivers queued alerts from the `outbox` collection: texts through Twilio, emails through Resend.

Each message is claimed atomically before sending, so several app workers can
run this loop without double-sending. Failed sends retry with backoff; a
number that texted STOP is switched off for alerts. A channel with no
provider configured is left queued, and its messages expire after 24 hours.

Run standalone with `python -m app.outbox`, or inside the app (TC_OUTBOX_WORKER).
"""
import asyncio
import logging
from datetime import timedelta

import httpx

from .cheers import apply_refills
from .deps import now
from .digest import DIGEST_HOUR, FOLLOW_UP_TEXT_HOUR, local_now, send_daily, send_follow_up_texts, send_weekly
from . import youtube as youtube_jobs

log = logging.getLogger("trade_circle.outbox")

MAX_ATTEMPTS = 5
BATCH = 50
POLL_SECONDS = 5
# Twilio error for a recipient who replied STOP.
TWILIO_OPTED_OUT = 21610


class SendError(Exception):
    def __init__(self, message: str, code: int | None = None, permanent: bool = False):
        super().__init__(message)
        self.code = code
        self.permanent = permanent


class TwilioSMS:
    def __init__(self, settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url="https://api.twilio.com",
            auth=(settings.twilio_account_sid, settings.twilio_auth_token),
            timeout=15,
            transport=transport,
        )

    async def send(self, to: str, body: str) -> str:
        data = {"To": to, "Body": body}
        if self.settings.twilio_messaging_sid:
            data["MessagingServiceSid"] = self.settings.twilio_messaging_sid
        else:
            data["From"] = self.settings.twilio_from_number
        try:
            res = await self._client.post(f"/2010-04-01/Accounts/{self.settings.twilio_account_sid}/Messages.json", data=data)
        except httpx.HTTPError as exc:
            raise SendError(f"network: {exc}") from exc
        if res.status_code >= 400:
            payload = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
            code = payload.get("code")
            # 4xx other than rate limiting will fail the same way on retry.
            raise SendError(payload.get("message", res.text[:200]), code, permanent=res.status_code < 500 and res.status_code != 429)
        return res.json()["sid"]

    async def deliver(self, msg: dict) -> str:
        return await self.send(msg["to"], msg["body"])

    async def aclose(self):
        await self._client.aclose()


class ResendEmail:
    """Plain-text email through Resend, using the same account settings as the Mind At Ease site."""

    def __init__(self, settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url="https://api.resend.com",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            timeout=15,
            transport=transport,
        )

    async def deliver(self, msg: dict) -> str:
        payload = {
            "from": f"{self.settings.email_from_name} <{self.settings.resend_from_email}>",
            "to": [msg["to"]],
            "subject": msg["subject"],
            # Plain text only: lead names come from the public form, so nothing is rendered as HTML.
            "text": msg["body"],
        }
        if self.settings.email_reply_to:
            payload["reply_to"] = self.settings.email_reply_to
        try:
            res = await self._client.post("/emails", json=payload)
        except httpx.HTTPError as exc:
            raise SendError(f"network: {exc}") from exc
        if res.status_code >= 400:
            payload = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
            raise SendError(payload.get("message", res.text[:200]), permanent=res.status_code < 500 and res.status_code != 429)
        return res.json().get("id", "")

    async def aclose(self):
        await self._client.aclose()


async def _claim(db, channel: str):
    current = now()
    return await db.outbox.find_one_and_update(
        {"channel": channel, "status": "queued", "next_attempt_at": {"$lte": current}},
        {"$set": {"status": "sending", "claimed_at": current}, "$inc": {"attempts": 1}},
        sort=[("next_attempt_at", 1)],
        return_document=True,
    )


async def _expire(db) -> None:
    await db.outbox.update_many(
        {"status": "queued", "expires_at": {"$lte": now()}}, {"$set": {"status": "expired"}}
    )


async def deliver_due(db, sms=None, email=None) -> int:
    """Send what is due on each configured channel. Returns the number of messages sent."""
    await _expire(db)
    sent = 0
    for channel, sender in (("sms", sms), ("email", email)):
        if sender is None:
            continue
        for _ in range(BATCH):
            msg = await _claim(db, channel)
            if msg is None:
                break
            try:
                provider_id = await sender.deliver(msg)
            except SendError as exc:
                await _failed(db, msg, exc)
                continue
            await db.outbox.update_one({"_id": msg["_id"]}, {"$set": {"status": "sent", "provider_id": provider_id, "sent_at": now()}})
            sent += 1
    return sent


async def _failed(db, msg: dict, exc: SendError) -> None:
    if exc.code == TWILIO_OPTED_OUT:
        await db.users.update_one({"_id": msg["user_id"]}, {"$set": {"alert_sms.active": False, "alert_sms.opted_out_at": now()}})
        status = "opted_out"
    elif exc.permanent or msg["attempts"] >= MAX_ATTEMPTS:
        status = "failed"
    else:
        status = "queued"
    update = {"status": status, "last_error": str(exc)[:300]}
    if status == "queued":
        update["next_attempt_at"] = now() + timedelta(seconds=30 * 2 ** msg["attempts"])
    await db.outbox.update_one({"_id": msg["_id"]}, {"$set": update})
    log.warning("%s %s %s: %s", msg["channel"], msg["_id"], status, exc)


async def run_forever(db, settings) -> None:
    sms = TwilioSMS(settings) if settings.twilio_ready else None
    email = ResendEmail(settings) if settings.email_ready else None
    if sms is None:
        log.info("Twilio not configured; text alerts stay queued until they expire")
    if email is None:
        log.info("Resend not configured; email alerts stay queued until they expire")
    if settings.youtube_ready:
        log.info("YouTube posting is on; up to %s uploads a day", settings.youtube_daily_uploads)
    if sms is None and email is None and not settings.youtube_ready:
        return
    summarized_on = texted_on = weeklied_on = refilled_on = None
    try:
        while True:
            try:
                here = local_now(settings)
                if refilled_on != here.date():
                    # The cheers monthly top-up sweep (per-member plan cycle dates).
                    await apply_refills(db, here.date())
                    refilled_on = here.date()
                if email is not None and summarized_on != here.date() and here.hour >= DIGEST_HOUR:
                    await send_daily(db, settings, here)
                    summarized_on = here.date()
                if email is not None and weeklied_on != here.date() and here.hour >= DIGEST_HOUR:
                    await send_weekly(db, settings, here)
                    weeklied_on = here.date()
                if sms is not None and texted_on != here.date() and here.hour >= FOLLOW_UP_TEXT_HOUR:
                    await send_follow_up_texts(db, settings, here)
                    texted_on = here.date()
                await deliver_due(db, sms, email)
                await youtube_jobs.deliver_due(db, settings)
            except Exception:
                log.exception("outbox pass failed")
            await asyncio.sleep(POLL_SECONDS)
    finally:
        for sender in (sms, email):
            if sender is not None:
                await sender.aclose()


if __name__ == "__main__":
    from motor.motor_asyncio import AsyncIOMotorClient

    from .config import load_settings

    logging.basicConfig(level=logging.INFO)
    _settings = load_settings()
    _db = AsyncIOMotorClient(_settings.mongo_url, tz_aware=True)[_settings.db_name]
    asyncio.run(run_forever(_db, _settings))
