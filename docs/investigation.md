# Investigation: Empire invoicing, email capacity, paid-tier features, benefits

Recorded October 23, 2026, for [`spec-gaps.md`](spec-gaps.md) sections 7–9. Each finding is labeled:

- **Code exists**: found in a repository, read but not run against live services.
- **Planned**: described in a spec, roadmap or TODO, with no working code.
- **Verified live**: confirmed working against the real service. **Nothing in this document is verified live.** No Empire host, Stripe, Twilio, Resend or Google account was reachable from this workspace.
- **Unknown**: couldn't be determined from here.

## 1. Which Empire app invoices

Invoicing lives in the **Momoempire** backend (the "AI office" / Mind At Ease Solutions site), not in Trade Circle. Trade Circle has no invoicing code.

| Capability | Status | Where |
|---|---|---|
| Estimates: create, edit, list, delete | Code exists | `routers/crm.py` (`/estimates`) |
| Estimates: send to customer | Code exists | `crm.py` `POST /estimates/{id}/send` |
| Invoices: create, list, mark paid, delete | Code exists | `crm.py` (`/invoices`) |
| Quote drafted from the tenant's price catalog, owner approval before sending | Code exists | `routers/call_to_payment.py` |
| Customer accepts a quote online → appointment + invoice | Code exists | `call_to_payment.py` |
| Overdue invoice reminders (per-invoice settings + scheduled job) | Code exists | `call_to_payment.py` `PUT /invoices/{id}/reminders` |
| Online card payments | Code exists | Stripe Connect Standard, direct charges to the contractor's own Stripe account, no platform application fee |
| Sync an invoice to bookkeeping (Ledger-Flow) | Code exists | `bookkeeping_link.py` |
| CSV export | Code exists | |
| Invoice PDF | **Not found** | no PDF generator in the invoicing code |
| Data isolation | Code exists | every query is scoped by `tenant_id` |
| Running in production | **Not live** | Momoempire's `DEPLOYMENT_READINESS.md` lists no host provisioned and Stripe, Twilio and cron settings missing |
| Trade Circle ↔ Empire connection | **Does not exist** | no account linking, API client or shared login in either repository |

**What free basic invoicing through Empire would take** (not built; decision needed): a Trade Circle member would need an Empire tenant (created on demand or linked to an existing one), a way to sign in to it from Trade Circle (shared login or a signed hand-off link), and agreement on which Empire screens a free member may use. Building a second invoicing system inside Trade Circle is ruled out by the spec.

Separate cost lines, as the spec asks:
- **Invoice creation**: Empire code; no per-invoice cost beyond hosting.
- **Email delivery**: Empire's `services/email.py` sends through **Resend** with the same variable names Trade Circle uses (`RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `EMAIL_FROM_NAME`, `EMAIL_REPLY_TO`). When the key isn't set it skips sending without failing. Not configured or verified live.
- **Reminders**: Empire cron job; uses the same email path.
- **AI help** (quote drafting, support assistant): Empire has AI code with its own metering (`usage.py`, `overage.py`); provider costs apply per use.
- **Payment processing**: Stripe's fees are charged to the contractor's Stripe account. Free invoicing must not be described as free payment processing.
- **Lead alerts**: invoice email must not turn on lead alerts for free members. Nothing links the two; keep it that way.

**Free invoice allowance**: none set. Competitors' invoice counts (for example Trade Hounds) are **unknown**: not verified from an official source here.

## 2. Email sending capacity

| Option | Published limits | Cost | Status for this owner |
|---|---|---|---|
| Resend Free | 3,000 emails/month, at most 100/day | $0 | Code exists in both apps; account and sending domain **unknown** |
| Resend Pro | 50,000/month, no daily cap | $20/month | Not set up |
| Google Workspace Gmail (per user) | 2,000 messages/day (rolling 24 h); 10,000 total recipients/day; 3,000 external unique recipients/day; trial accounts 500/day | included in Workspace | Edition, admin access and sender setup **unknown**: owner must check |
| Google Workspace SMTP relay | 10,000 messages per user per 24 h; 100 recipients per message | included in Workspace | Requires admin setup; **unknown** |

Notes:
- Workspace **storage** (pooled per edition) has nothing to do with how many emails can be sent.
- Gmail's per-user limits are meant for people sending mail, not app notification volume; the SMTP relay is the Workspace route intended for apps. Either way the limits are shared by everything the owner sends from that account, including Empire and Mind At Ease mail.
- Trade Circle's outbox already queues, retries with backoff and claims each message atomically so a message isn't sent twice; delivery status is recorded per message. Empire's sender has no queue: it sends inline.
- Today's Trade Circle email volume per paid member is at most one daily summary plus instant lead alerts and handoff notices. At 100 paid members that's roughly 3,000+ emails a month, which already reaches the Resend Free monthly limit. Recommendation before choosing an allowance: start on Resend Free while volume is small, and decide between Resend Pro ($20/month) and the Workspace SMTP relay after the owner confirms the Workspace edition and admin access.

## 3. $3 Starter features: which work

| Feature | Trade Circle | Empire (Momoempire) |
|---|---|---|
| Paid lead alerts (text and email) | **Code exists**, tested; Twilio and Resend not configured | Separate system |
| Custom domain via CNAME | **Not built** | Code exists: `domains.py` CNAME wizard and DNS check, per tenant |
| Google Business Profile sync | **Not built** | **Planned** only: `reputation.py` has `TODO(LIVE): connect Google Business Profile API` |
| Time tracking | **Not built** | Code exists: `time_tracking.py` timesheets per tenant |
| YouTube auto-posting | **Not built** | **Not built**: no YouTube code |
| Daily summary email and afternoon follow-up text | Code exists, tested | — |

So of the five advertised $3 items, only paid lead alerts exist in Trade Circle. The CNAME and time-tracking code in Empire would need the same account connection as invoicing before Trade Circle members could use it. **Decision needed**: whether the $3 description should list only what works today.

### YouTube auto-posting requirements (not built)
- Upload uses the YouTube Data API `videos.insert`, which needs the member's own Google sign-in (OAuth) with the YouTube upload scope.
- Quota: since June 1, 2026 uploads count against a separate "Video Uploads" quota, 100 calls/day by default for the whole project, shared by all members. More needs a quota request.
- Verification: videos uploaded by API projects created after July 28, 2020 that haven't passed Google's compliance audit are restricted to **private**. Public publishing can't be promised until the audit passes. Google's documentation is partly inconsistent on details; recheck before building.
- The flow in the spec (confirm title, description, visibility and channel before sending) is compatible with this.

### Effect of free basic invoicing on tier descriptions
If basic invoicing becomes free, the $9 tier's "Empire tie-in" line needs rewording to the parts that stay paid (for example payments, reminders, AI help or bookkeeping sync), but that is a pricing decision and nothing has been changed.

## 4. Benefits marketplace

No partner integration exists in either repository. Momoempire has a financing **demo** (`financing.py`, Wisetack named as a target, not connected). No insurance, retirement, payroll or benefits provider, cost or eligibility rule was found. Nothing was enrolled or purchased.

## 5. Break Room research

- **YouTube embedded player rules**: viewport at least 200 × 200 px; no autoplay until visible; no overlays covering the player; no changes not described in the API documentation. ([Required Minimum Functionality](https://developers.google.com/youtube/terms/required-minimum-functionality))
- **Games**: open-source games checked for licensing. `2048` by Gabriele Cirulli is MIT-licensed (commercial use and embedding allowed with the copyright notice; no ads, no tracking, no sound). `clumsy-bird` and `hextris` are GPL-3.0: usable, but serving them obliges us to offer their source; left out to keep things simple. Commercial game portals' embed terms weren't accepted on the owner's behalf.
- **Giveaways and public offers**: none seeded. Current giveaways and deals couldn't be confirmed with truthful last-checked dates and sharing terms from here; the admin adds them with the required fields.

## Sources
- [Google Workspace: Gmail sending limits](https://support.google.com/a/answer/166852?hl=en)
- [Google Workspace: SMTP relay limits](https://support.google.com/a/answer/2956491?hl=en)
- [YouTube Data API: videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert)
- [YouTube Data API: revision history](https://developers.google.com/youtube/data/revision_history)
- [YouTube Required Minimum Functionality](https://developers.google.com/youtube/terms/required-minimum-functionality)
- [Resend pricing](https://resend.com/pricing)
- [Resend account quotas and limits](https://resend.com/docs/knowledge-base/account-quotas-and-limits)
- [2048 source and MIT license](https://github.com/gabrielecirulli/2048)
