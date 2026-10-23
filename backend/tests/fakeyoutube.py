"""A stand-in for Google's OAuth endpoints and the YouTube Data API, for tests.

Records every request and answers like Google would. The refresh token it hands
out is REFRESH_TOKEN; presenting anything else at refresh time gets an
invalid_grant, like a revoked token would.
"""
import itertools
import json

import httpx

YOUTUBE_SETTINGS = dict(
    youtube_client_id="client-id",
    youtube_client_secret="client-secret",
    youtube_redirect_uri="https://testserver/api/youtube/callback",
)
REFRESH_TOKEN = "rt-secret-1"
CHANNEL = {"id": "chan-1", "title": "Bright Spark TV"}


class FakeYouTube:
    def __init__(self):
        self.requests = []
        self.uploads = []  # {"metadata": ..., "bytes": n} for each finished upload
        self.revoked = []
        self.fail_uploads = 0  # fail this many upload PUTs with a 500, then succeed
        self._ids = itertools.count(1)
        self._pending = {}

    def transport(self):
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        form = {}
        if request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
            from urllib.parse import parse_qsl

            form = dict(parse_qsl(request.content.decode()))
        self.requests.append({"method": request.method, "host": host, "path": path, "form": form, "headers": dict(request.headers)})
        if host == "oauth2.googleapis.com" and path == "/token":
            if form.get("grant_type") == "authorization_code":
                return httpx.Response(200, json={"access_token": "at-1", "refresh_token": REFRESH_TOKEN, "expires_in": 3600, "token_type": "Bearer"})
            if form.get("grant_type") == "refresh_token":
                if form.get("refresh_token") != REFRESH_TOKEN:
                    return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
                return httpx.Response(200, json={"access_token": "at-2", "expires_in": 3600, "token_type": "Bearer"})
        if host == "oauth2.googleapis.com" and path == "/revoke":
            self.revoked.append(form.get("token"))
            return httpx.Response(200, json={})
        if host == "www.googleapis.com" and path == "/youtube/v3/channels":
            return httpx.Response(200, json={"items": [{"id": CHANNEL["id"], "snippet": {"title": CHANNEL["title"]}}]})
        if host == "www.googleapis.com" and path == "/upload/youtube/v3/videos":
            session = f"https://upload.youtube.test/session-{next(self._ids)}"
            self._pending[session] = json.loads(request.content)
            return httpx.Response(200, headers={"Location": session})
        if host == "upload.youtube.test":
            if self.fail_uploads > 0:
                self.fail_uploads -= 1
                return httpx.Response(500, json={"error": {"message": "backend exploded"}})
            self.uploads.append({"metadata": self._pending.get(str(request.url)), "bytes": len(request.content)})
            return httpx.Response(201, json={"id": f"vid-{next(self._ids)}", "snippet": {}, "status": {}})
        return httpx.Response(404, json={"error": {"message": f"unhandled {host}{path}"}})
