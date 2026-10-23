# Trade Circle
A networking and business site for small contractor businesses. Part of Mind At Ease Solutions, served at `tradecircle.mindatease.com`.

- Product spec: [`docs/spec.md`](docs/spec.md)
- Community expansion spec: [`docs/spec-community.md`](docs/spec-community.md)
- Build status and order: [`docs/roadmap.md`](docs/roadmap.md)

## Stack
Same stack as Empire/LedgerFlow, so security patterns carry over: FastAPI, MongoDB (Motor), argon2 password hashing, JWT sessions, Stripe Connect (planned).

## Run it
The backend serves the API, the public pages (`/p/<slug>`) and the contractor dashboard (`/app`). Build the dashboard once, then start the backend.
```bash
cd frontend && npm ci && npm run build && cd ..
```
For dashboard work with live reload, run `npm run dev` in `frontend/` alongside the backend; Vite forwards API calls to port 8000.

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
export TC_JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
export TC_MONGO_URL=mongodb://localhost:27017
export TC_ENFORCE_HTTPS=false   # local dev only
.venv/bin/uvicorn app.main:create_app --factory --reload
```
The dashboard is then at `http://localhost:8000/app`, API docs at `/docs`, and a contractor's public page at `/p/<slug>`.

Operator commands, run on the server:
```bash
.venv/bin/python -m app.cli make-admin someone@example.com   # also revoke-admin, disable, enable
.venv/bin/python -m app.cli seed-suppliers                   # starter supplier listings; safe to rerun
```

| Variable | Default | Purpose |
|---|---|---|
| `TC_JWT_SECRET` | none, required | Signs session tokens. At least 32 characters. |
| `TC_MONGO_URL` | `mongodb://localhost:27017` | Database connection. |
| `TC_DB_NAME` | `trade_circle` | Database name. |
| `TC_ENFORCE_HTTPS` | `true` | Redirect HTTP to HTTPS and send HSTS. |
| `TC_TRUST_PROXY` | `false` | Trust `X-Forwarded-*` headers. Enable only behind our own proxy. |
| `TC_ACADEMY_URL` | unset | Academy link in the page footer. Hidden until set. The Academy lives on the Mind At Ease site (Momoempire repo). |
| `TC_PUBLIC_URL` | `https://tradecircle.mindateasesolutions.com` | Site address used in links inside text alerts. |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | unset | Twilio account. Same names as the Mind At Ease site, so one account can serve both. |
| `TWILIO_MESSAGING_SID` or `TWILIO_FROM_NUMBER` | unset | Who texts are sent from. A Messaging Service is preferred. |
| `RESEND_API_KEY`, `RESEND_FROM_EMAIL` | unset | Resend for paid-plan email alerts. Same names as the Mind At Ease site. `EMAIL_FROM_NAME` (default "Trade Circle") and `EMAIL_REPLY_TO` are optional. |
| `TC_MEDIA_DIR` | `media/` beside `backend/` | Where uploaded photos and video clips are stored. Back it up. Video clips need `ffmpeg` and `ffprobe` installed on the server; without them clip uploads are switched off. |
| `TC_TIMEZONE` | `America/Chicago` | Calendar for "today" and the Monday-to-Sunday handoff week. |
| `TC_RATE_COMPARISONS` | `false` | Publish aggregated pay and billing-rate comparisons. Leave off until the data-sharing review is done; submissions are collected either way. |
| `TC_AI_API_KEY`, `TC_AI_MODEL` | unset | AI provider key (Anthropic) and model for the contractor AI helper and photo part lookup. Nothing is sent to a provider until these, both prices and a budget are set. |
| `TC_AI_INPUT_PRICE`, `TC_AI_OUTPUT_PRICE` | `0` | The model's current price in USD per million input and output tokens, used to reserve and reconcile spending. |
| `TC_AI_MONTHLY_BUDGET` | `0` | Shared monthly AI helper budget in USD. Requests stop when it can't cover the most a request could cost. |
| `TC_AI_DAILY_LIMIT`, `TC_AI_MONTHLY_LIMIT` | `3`, `10` | Successful AI helper answers per member per day and per calendar month (both apply, in `TC_TIMEZONE`). |
| `TC_AI_MAX_OUTPUT_TOKENS` | `2000` | Upper bound on each answer (thinking included). |
| `TC_PARTS_MONTHLY_BUDGET`, `TC_PARTS_DAILY_LIMIT`, `TC_PARTS_MONTHLY_LIMIT` | `0` | Photo part identification's own budget and allowance. Off until all are set; manual part-number search always works. |
| `TC_OUTBOX_WORKER` | `true` | Send queued alerts from inside the app. With Twilio unset, alerts stay queued and expire after 24 hours. |
| `TC_YOUTUBE_CLIENT_ID`, `TC_YOUTUBE_CLIENT_SECRET`, `TC_YOUTUBE_REDIRECT_URI` | unset | The site's Google Cloud OAuth client for the YouTube integration. Until all three are set, YouTube posting is off and Settings says so. The redirect URI must exactly match the one registered in Google Cloud (for example `https://your-site/api/youtube/callback`). |
| `TC_YOUTUBE_DAILY_UPLOADS` | `6` | Site-wide cap on YouTube uploads per day. One upload costs 1,600 of the Google project's 10,000 daily quota units; posts past the cap wait and go up the next day instead of failing. |
| `TC_ENCRYPTION_KEY` | unset | Key that encrypts members' stored YouTube sign-in tokens. Use a Fernet key (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`); any other value is hashed into a key. When unset it is derived from `TC_JWT_SECRET`. Changing it makes stored tokens unreadable, so members would need to reconnect their channels. |

## Tests
```bash
cd frontend && npm test && cd ..                                 # dashboard
cd backend
.venv/bin/pytest -q                                              # in-memory database
TC_TEST_MONGO_URL=mongodb://localhost:27017 .venv/bin/pytest -q  # real MongoDB; each test uses and drops its own database
```
CI runs all three on every push.
