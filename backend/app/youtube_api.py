"""A small YouTube client: OAuth with Google and uploads through the YouTube Data API v3.

This is a YouTube integration, not a partnership. Calls go straight to Google's
REST endpoints with httpx, like the Stripe, Twilio and Resend clients. Tests
swap in a fake transport (app.state.youtube_transport), so nothing here needs a
Google account until the site's OAuth client is configured.

Quota: one videos.insert costs 1,600 units of the project's 10,000 daily units.
app/youtube.py counts uploads per day and holds the rest for the next day.
"""
import json
from urllib.parse import urlencode

import httpx

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3"
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"


class YouTubeError(Exception):
    """A Google/YouTube call failed. `permanent` failures (bad or revoked token,
    a file YouTube refuses) won't succeed on retry; the rest get the outbox's backoff."""

    def __init__(self, message: str, status: int | None = None, permanent: bool = False):
        super().__init__(message)
        self.status = status
        self.permanent = permanent


def _failed(res: httpx.Response) -> YouTubeError:
    try:
        error = res.json().get("error") or {}
    except ValueError:
        error = {}
    if isinstance(error, dict):
        message = error.get("message") or res.text[:200]
        reasons = [e.get("reason", "") for e in error.get("errors") or []]
    else:  # the token endpoint returns {"error": "invalid_grant", "error_description": ...}
        message = res.json().get("error_description") or str(error)
        reasons = [str(error)]
    permanent = res.status_code < 500 and res.status_code != 429
    if "invalid_grant" in reasons:
        permanent = True
    return YouTubeError(str(message)[:300], res.status_code, permanent)


class YouTube:
    def __init__(self, client_id: str, client_secret: str, transport: httpx.AsyncBaseTransport | None = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.transport = transport

    def consent_url(self, redirect_uri: str, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            # offline + consent: Google returns a refresh token the member can revoke any time.
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    async def _post_form(self, url: str, data: dict) -> dict:
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=30) as client:
                res = await client.post(url, data=data)
        except httpx.HTTPError as exc:
            raise YouTubeError(f"network: {exc}") from exc
        if res.status_code >= 400:
            raise _failed(res)
        return res.json()

    async def exchange_code(self, code: str, redirect_uri: str) -> dict:
        return await self._post_form(TOKEN_URL, {
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })

    async def refresh(self, refresh_token: str) -> str:
        body = await self._post_form(TOKEN_URL, {
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
        })
        return body["access_token"]

    async def revoke(self, token: str) -> None:
        async with httpx.AsyncClient(transport=self.transport, timeout=15) as client:
            await client.post(REVOKE_URL, data={"token": token})

    async def my_channel(self, access_token: str) -> dict:
        async with httpx.AsyncClient(transport=self.transport, timeout=15) as client:
            res = await client.get(f"{API}/channels", params={"part": "snippet", "mine": "true"}, headers={"Authorization": f"Bearer {access_token}"})
        if res.status_code >= 400:
            raise _failed(res)
        items = res.json().get("items") or []
        if not items:
            raise YouTubeError("That Google account has no YouTube channel.", permanent=True)
        return {"id": items[0]["id"], "title": items[0]["snippet"]["title"]}

    async def upload(self, access_token: str, data: bytes, title: str, description: str, privacy: str) -> dict:
        """Resumable upload of one clip. Returns the new video's id and watch URL."""
        metadata = {"snippet": {"title": title, "description": description}, "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}}
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(len(data))}
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=600) as client:
                start = await client.post(f"{UPLOAD_API}/videos", params={"uploadType": "resumable", "part": "snippet,status"}, content=json.dumps(metadata), headers=headers)
                if start.status_code >= 400:
                    raise _failed(start)
                location = start.headers.get("location")
                if not location:
                    raise YouTubeError("YouTube didn't start the upload.", permanent=False)
                res = await client.put(location, content=data, headers={"Content-Type": "video/mp4"})
        except httpx.HTTPError as exc:
            raise YouTubeError(f"network: {exc}") from exc
        if res.status_code >= 400:
            raise _failed(res)
        video_id = res.json()["id"]
        return {"id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}"}


def for_state(state) -> YouTube:
    """The client for an app: real Google endpoints, or a test's fake transport."""
    settings = state.settings
    return YouTube(settings.youtube_client_id, settings.youtube_client_secret, getattr(state, "youtube_transport", None))
