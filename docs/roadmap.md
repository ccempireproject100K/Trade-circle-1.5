# Trade Circle roadmap
Build status against [`spec.md`](spec.md) and [`spec-community.md`](spec-community.md). Updated October 23, 2026 (slice 11).
"Built" means working code with passing tests on both an in-memory and a real MongoDB 7.0 database. Nothing is deployed.

## Slice 1 — foundation (built)
| Area | What exists |
|---|---|
| Accounts | Signup, login, `/api/me`. Each signup creates a contractor profile on the free tier. |
| Security | argon2 password hashing; JWT sessions; HTTPS redirect plus HSTS; per-IP and per-account login rate limits; per-IP quote rate limit; contractor/admin roles, read from the database on each request; every record query scoped to its owner, and other owners' records return 404. |
| Audit log | Middleware writes every write request, plus inbox and admin reads, to the `audit_log` collection: user ID, timestamp, action, affected record, status. Nothing in the app updates or deletes it. |
| Landing page (#2) | `GET /api/p/{slug}`: the scannable layer, with brand color, badges, `tel:` and FaceTime links, and the first 6 portfolio photos. |
| Full profile | `GET /api/p/{slug}/full`: the deep layer, with sections in the contractor's own order (auto-reflow fills in missing sections). |
| Badges | Unverified badge; lapsed-cert badges; re-certification banner for 3 days after renewal; insurance status: none, pending, insured or expired. |
| Insurance verification | Contractor submits proof; admin verifies it; any new submission goes back to pending. |
| Photo portfolio (#1) | Add, drag-and-drop reorder and delete photos. HTTPS image URLs only, for now. |
| Request a quote | Public form with a honeypot field that silently drops bot submissions; leads land in the contractor's inbox with status new, contacted, won or lost. |
| Job sheet (#4) | Create, list, update and delete jobs, scoped to their owner. |

## Slice 2 — hardening and public pages (built)
| Area | What exists |
|---|---|
| Lead alerts | Paid plans only; free-plan contractors log in to see leads. Each new quote request queues an email alert and, if the contractor opted in with consent recorded, a text alert. Texts go out through Twilio (shared account settings with the Mind At Ease site), claimed atomically so several workers never double-send, retried with backoff, switched off when the contractor replies STOP, and dropped after 24 hours rather than sent late. Emails go out through Resend (slice 9). |
| Editing | Optional profile and job fields can be cleared by sending null; required ones can't. |
| Publish switch | Contractors can hide their page. Hidden pages, and pages of disabled accounts, return "not found" and take no quotes. |
| Sessions | "Sign out everywhere", and password change signs out every other device. |
| Quote flood cap | Per-contractor limit on quote requests, on top of the per-sender limit. |
| Signup | Retries if two same-named businesses sign up at once; never leaves an account without a profile. |
| Operator commands | `python -m app.cli make-admin / revoke-admin / disable / enable <email>`, each written to the audit log. |
| Phone numbers | US numbers accepted as people type them, e.g. `(512) 555-0199`, and stored in international format. |
| Public pages | Server-rendered landing page at `/p/{slug}` and full profile at `/p/{slug}/full`: mobile-first, brand colors with readable text, badges, re-cert banner, Call button, FaceTime button on Apple devices only, photo grid, working quote form, search-engine data (schema.org LocalBusiness), strict content security policy, Academy link in the footer when `TC_ACADEMY_URL` is set. Checked in Chromium at iPhone, Android and desktop sizes. |

## Slice 3 — contractor dashboard (built)
| Area | What exists |
|---|---|
| App | React app at `/app`, built with Vite. Phone-first with a bottom tab bar; top tabs on desktop. Light and dark mode. |
| Sign-in | Signup and login. The session is an HttpOnly cookie, so page scripts never see the token; cookie-based writes must carry a CSRF header. API clients can still use Bearer tokens. |
| Home | New-lead and open-job counts, page link with copy button, upcoming jobs, plan note (free plan: leads wait in the Leads tab). |
| Leads | Filter by status, Call/Text/Email buttons, change status, and "Make job", which copies the lead into the job sheet and marks it won. |
| Jobs | Add jobs with customer, address, date and dollar estimate; change status and date; delete; open and done tabs. |
| Profile | Live/hidden switch, details (tagline, trade, phone, FaceTime, brand color, about), drag-and-drop section order that works with a finger, licenses with renewal dates, insurance submission. |
| Photos | Add by link, drag-and-drop or button reorder, delete. |
| Settings | Text-alert opt-in with consent wording (paid plans), password change, sign out, sign out everywhere. |
| Checks | 8 component tests; a 14-step end-to-end run in Chromium against the real backend and MongoDB at iPhone and desktop sizes, from signup through a homeowner's quote to a job. |

## Slice 4 — job handoffs and vacations (built)
Spec: "Job handoffs" in [`spec.md`](spec.md). Rules live in `backend/app/handoffs.py`.

| Area | What exists |
|---|---|
| Weekly limits | 3 outgoing handoffs per week in total and 2 to the same member. The week runs Monday to Sunday on Trade Circle's time zone (`TC_TIMEZONE`, default America/Chicago). The check and the count happen in one database step, so simultaneous sends can't slip past (8 simultaneous tries → exactly 3 succeed). Proposed, accepted and completed handoffs count; declined or withdrawn ones give the slot back. |
| At the limit | Sending is blocked with a message giving the reset time (for example "Monday, Oct 26, 12:00 AM CDT") and saying extra coverage can be arranged outside Trade Circle. Jobs, leads, profile and pages keep working. |
| Vacations | Settings → Vacation: first day, last day and a required note. At most 14 days. Overlapping or back-to-back entries are joined and may not pass 14 days in a row. An upcoming vacation can be cancelled; a current one can be ended early, and stays on record. |
| Vacation exception | While a vacation runs, the weekly limits are lifted. Handoffs sent then are marked "sent during vacation" and don't use the normal allowance, so normal limits are back in full the day after it ends. |
| Proposals | A member picks an open job, a member (searched by name), dates and a note. The recipient sees the job, dates, address, estimate and note, and accepts or declines. The customer's name and phone are shared only on acceptance. Accepting copies the job to the recipient's job sheet and marks the sender's copy "Handed off". The recipient marks it completed. Sender, recipient, dates, response and completion times are all stored, and every change is in the audit log. |
| Alerts | Paid-plan recipients get an email or text when a job is offered; senders when it is accepted, declined or completed. Free-plan members see waiting offers on Home and in Handoffs. |
| Review | `GET /api/admin/handoffs/patterns` (admins): pairs of members by number of handoffs over recent weeks, both directions, flagged for a person to review. It changes nothing for the members. There is no partner or group feature. |
| Checks | 17 backend tests (each limit, the reset, vacation dates, the 14-day maximum, back-to-back joins, the automatic return, consent, privacy, review report, simultaneous sends), each limit deliberately broken once to confirm the tests catch it; 5 dashboard tests; a 19-step browser run with three members. |

## Slice 5 — photo uploads (built)
| Area | What exists |
|---|---|
| Upload | Photos → "Add photos" opens the camera or photo library; several photos at once, with a progress bar each. Captions are edited in place. Adding by link is still there, tucked away. |
| Clean-up | Every photo is rebuilt from its pixels, so GPS location and all other metadata are removed. Sideways phone photos are turned upright, large ones shrunk to 1600 px, and a 600 px square thumbnail is made for grids. |
| Checks on the file | JPEG, PNG and WebP only, judged by the content, not the file name. Up to 15 MB and 60 megapixels. Up to 200 photos per member. |
| Storage | Saved under `TC_MEDIA_DIR` (default `media/` beside `backend/`) and served at `/media`. Deleting a photo deletes its files. Public pages use the thumbnails in the grid and link to the full photo. |
| Checks | 9 backend tests (including a real GPS-tagged, rotated phone photo), and a 10-step browser run through the real file picker. |

## Slice 6 — community core and Supplies & Vendors (built)
| Area | What exists |
|---|---|
| Community posts | One shared post system for supply questions, supplier experiences and suggestions, projects, lessons, equipment and meetups: comments, trade tags, photos (metadata removed), search, ZIP or "City, ST" location with distance filter, reports and a moderator queue (`/api/admin/reports`). |
| Location data | ZIP and city coordinates and each ZIP's state from public Census files (`backend/app/data`, rebuilt by `scripts/build_geo.py`). No paid maps or geocoding. |
| Supplies & Vendors | Member recommendations on top (ask with an area, share good or bad experiences, suggest suppliers), supplier directory below with area, distance, category, name and ships-to filters. |
| Directory | Facts with their sources, kept apart from member opinions; wording says exactly what was checked and what wasn't, never "verified" or "trusted"; alphabetical, or by distance when an area is given, with no placement for starter listings. Five starter listings seeded from official websites (`python -m app.cli seed-suppliers`). Moderators add listings, usually from member suggestions, and must give a source. |
| Removal requests | Public page `/suppliers/<id>/remove`. A moderator must record how the request was confirmed before approving. Then the listing's details are deleted; member posts and replies stay with the supplier's name, website, address and street name replaced by "[supplier]", photos hidden, and each changed item flagged for a moderator to double-check. No reveal feature. |

## Slice 7 — guided walkthroughs and lessons (built)
| Area | What exists |
|---|---|
| Share a project | One question at a time, each skippable, with Back, Skip and Save draft; before and finished photo steps; review screen with the member's own answers under headings, trade tags, feature-on-profile option and privacy reminder; preview, then an explicit Publish. |
| Quick lesson | Four short questions plus optional photos, same component. |
| Drafts | Autosave about a second after each change, a copy kept on the phone immediately, an immediate save when leaving the screen or switching apps, resume at the same question, recovery of changes that never reached the server. |
| Tap-to-talk | Browser speech recognition, started only by a tap, with a recording indicator and Stop; stops when leaving the step. Typing works when voice is unavailable or the microphone is declined. |
| Profile | Featured, published walkthroughs appear in a "Featured projects" section of the public full profile. |

## Slice 8 — tracker, equipment, mentoring, meetups, messaging (built)
| Area | What exists |
|---|---|
| Follow-up tracker | Work → Follow-ups extends the quote inbox: entries added from calls, texts or conversations, private notes, follow-up dates, waiting / followed up / won / closed, all, upcoming and overdue views. Owner-only. Old statuses converted on start. No reminders are sent (see decisions). |
| Equipment | Experiences (use, durability, problems, repairs, buy again) with required disclosure of any seller, sponsor or employer connection, or questions; product and model search; optional supplier link; shown as opinion. |
| Messaging | Consent first: a request the other member accepts before anything can be sent. Block (stops requests and messages both ways), report member or message. Used to contact a post's author (for example, a reviewer). |
| Mentoring | Opt in as willing to help and/or looking for a mentor, with topics, experience, availability and a preferred contact shared only when the member accepts an introduction. Pause or remove. Wording says it's voluntary and not certified. |
| Meetups | Title, description, date, time, time zone, general location, host, RSVP (going / maybe / can't go), attendee list, host updates and cancellation; upcoming, area and trade filters. |
| Notifications | In-app activity on Home for message requests, acceptances, messages and meetup updates. No email or text for community activity. |

## Slice 9 — email alerts and daily summary (built, delivery not yet verified live)
- Paid-plan lead emails go out through Resend, using the same `RESEND_API_KEY` / `RESEND_FROM_EMAIL` settings as the Mind At Ease site; plain text only, retries and expiry as for texts. Not yet tested against a live Resend account.
- Daily summary (decided Oct 23): paid plans get one email from 7 AM Central, only when there's something new (community activity and follow-ups due today or overdue; handoff notices are sent as they happen and not repeated). Members can turn it off. Paid members with text alerts on also get at most one afternoon text (from 2 PM) when follow-ups are still due. Free plans: in-app only. (Slice 12 later put all texts under a per-plan daily budget, made the morning summary a text too, and gave the free plan a weekly update email — see below.)

## Slice 10 — competitor-gap additions (built; see [`spec-gaps.md`](spec-gaps.md) and [`investigation.md`](investigation.md))
- **Pay & rates** (Work → Rates): private wage and billing-rate submissions (only the state is kept), statewide comparisons from at least 5 members using figures over 90 days old, ranges with sample size, months and a self-reported label. Publishing is off until the data-sharing review (`TC_RATE_COMPARISONS`). Cost calculator with markup vs margin runs only in the browser.
- **Compare screen, three separate sections** (decided Oct 23):
  - *Government wage data*: BLS Occupational Employment and Wage Statistics, May 2025, for each trade's occupations in the member's metro or non-metro area (ZIP or city), with statewide figures where BLS publishes nothing for the area. Employee pay only. Available now. Rebuild each spring with `scripts/build_wages.py`.
  - *Outside estimates*: ranges published by cost guides and other sites, added by any member with the source link and checked date, copied unchanged. The member who added one can edit it. Older than 180 days is marked "may be out of date". Shown only under what contractors charge.
  - *Community corrections*: anyone else suggests a correction (new figures, or "the source no longer shows this") with a reason. Other members open the source and confirm or dispute, with an optional note. It's applied once 2 other members confirm and confirmations outnumber disputes; corrections made against an older version are retired when another one is applied. Moderators can apply or reject. History shows who suggested and who confirmed each change; members report bad entries and moderators hide them.
  - *From Trade Circle members*: the private, aggregated figures described above, still off until the review.
- **Hiring**: job openings are their own community post kind with role, type, pay, requirements, how to apply and apply-by date; filled or past-date openings leave search.
- **Part lookup** (Supplies → part lookup): model or part-number search across members' posts, exact model matches kept apart from mentions, a ready-to-send supplier question. Photo reading is built but off until its own budget and allowance are set.
- **AI helper**: 3 successful answers a day and 10 a calendar month per member, enforced atomically on the server; shared monthly budget with reserve-then-reconcile; failed requests don't use the allowance; only counts and costs stored, never questions. Off until a key, model, prices and budget are set.
- **Team** (Profile → Team): optional company accounts with admins and contributors, explicit permissions (profile, portfolio, follow-ups, jobs), acceptance, removal, change history, and opt-in public linking.
- **Break Room**: YouTube music player, the 2048 game, moderator-curated public offers and giveaways, member spot and deal suggestions, anonymous daily usage counts.
- **Walkthrough video clips**: existing clips up to 3 minutes, re-encoded so no metadata survives, with preview, trim and remove-sound before publishing.

## Slice 11 — customer reviews (built)
| Area | What exists |
|---|---|
| Who can review | A marketplace customer who chose a contractor, from their private request link (`/request/<token>`) — no account. The choice now records which request each inbox lead came from (`marketplace_request_id`), so the lead behind a link can be found again. |
| When | One review per lead (a unique index on `reviews.lead_id` enforces it in the database), and only once the lead is marked won or a job made from it is done. Jobs made from the follow-ups screen now carry `quote_id`, so "the linked job" is a real link. Before that, the status page shows no form and a direct post records nothing. |
| The review | 1–5 stars plus text (up to 1,000 characters). Shown publicly under the customer's first name and last initial only — never their full name or contact details. Same abuse guards as the quote form: the shared per-address rate limit and a honeypot that fakes success. The contractor gets an in-app notification. |
| Public pages | `GET /api/p/{slug}` and `/full` include the count, the average and the newest reviews (3 on the landing layer, 10 on the full profile), with the contractor's responses. The server-rendered pages show the same, and the landing page's schema.org data gains an `AggregateRating` once there is a review, so search results can show stars. |
| Dashboard | Profile → Reviews: the average, every review (hidden ones included, marked), a public response the contractor can post and edit, and a flag with an optional note for the moderators. |
| Moderation | Flagging keeps the review public and in the average until a moderator acts. `GET /api/admin/reviews` is the queue (flagged by default); admins hide (off the page and out of the average) and unhide there. Nothing about reviews is tier-gated: they are in `FREE_FEATURES`, on every plan. |
| Checks | 7 backend tests (too-early and duplicate posts, the won and job-done openings, validation and honeypot, response and edit, other owners locked out, flag → hide → unhide, aggregate math and the rating markup) and 4 dashboard tests (display, respond, flag, empty state). |

## Slice 12 — Text budget and the free weekly update (built)

Owner decision, 2026-10-23: texts are capped per member per day, by plan, and
the free plan gets one weekly update. Before this slice an instant text went
out for every alert event, which was never the deal.

- **Budgets** (`tiers.SMS_DAILY_BUDGET`, the single source): Starter 1 text a
  day, Full 2, free 0 — counted on the TC_TIMEZONE calendar day and claimed
  atomically in `notify.claim_sms` (a per-member-per-day counter, the same
  shape as the AI budget claim), so two events racing can't overspend the day.
  An event over budget still emails and still shows in the app; only the text
  is skipped. Emails are never capped.
- **The rundown is the first text.** The daily summary now also queues as a
  text for paid members who turned texts on, and takes the day's first slot.
  Instant alert texts (new lead, marketplace choice, handoff, payment) hold
  one slot back for it — in practice only Full members get them, as their
  second text. The afternoon follow-up text likewise only goes out while the
  day's allowance lasts. New-review alerts were never instant and stay that
  way: they ride the rundown.
- **Free plan: one weekly update email.** Monday from 7 AM local, the same
  summary over the last 7 days (community activity, follow-ups due/overdue),
  only when there's something new, claimed per week like the daily jobs are
  per day. Never a text. The Settings summary toggle controls it, same as the
  daily summary on paid plans — a member is on exactly one cadence:
  free is weekly, paid is daily.
- Settings copy and plan labels now say what actually happens per plan
  (Starter: "One text a day: your morning rundown"; Full: "Up to two texts a
  day: your morning rundown, plus one more").

## Slice 13 — YouTube auto-posting (built; runs once the operator connects a Google project)
| Area | What exists |
|---|---|
| Connect | Settings → YouTube. Starter and Full members connect their own channel through Google's consent screen (scopes `youtube.upload` and `youtube.readonly`, so the channel's name can be shown back). It is a YouTube integration, not a partnership. Only a refresh token is stored, encrypted at rest (Fernet; `TC_ENCRYPTION_KEY`). Disconnecting revokes the token at Google, deletes it here, and cancels anything still queued. |
| Posting | In the clip editor, "Also post this clip to my YouTube channel" reveals the confirm step — title (required), description, and visibility (public, unlisted or private; unlisted by default). Nothing posts before that confirmation, per spec-gaps §8. The upload runs in the background on the outbox pattern (`youtube_jobs`: atomic claim, backoff, 5 attempts), records the YouTube video id and watch URL on the clip, and shows queued / posting / posted / failed-with-reason next to the clip. A failed upload never touches the local clip. |
| Quota | One upload costs 1,600 of the Google project's 10,000 daily quota units. A site-wide daily counter (`TC_YOUTUBE_DAILY_UPLOADS`, default 6) holds extra posts for the next day instead of letting them fail, and logs each hold. |
| Switch | Off until `TC_YOUTUBE_CLIENT_ID`, `TC_YOUTUBE_CLIENT_SECRET` and `TC_YOUTUBE_REDIRECT_URI` are all set, the same posture as the AI helper: while off, Settings says so plainly, the clip editor stays silent, and the API answers 503. |
| Checks | 10 backend tests — connect stores the token encrypted (never plaintext in the database, never in any API response), status, disconnect and revoke, the free-plan tier gate, a confirmed post recording the video id and URL through a fake Google, retry with backoff, a revoked token failing with a reconnect flag, and the daily cap holding the extra post for tomorrow — plus 8 dashboard tests (card states: off, wrong plan, connect, connected, disconnect; the confirm step appearing only after opt-in; posted and failed status display). |
| Before real posting | **Uploads from a Google project that has not passed Google's verification/audit are forced to private by YouTube**, whatever visibility the member picks. The operator has to finish Google's OAuth verification and the YouTube API compliance audit for the project before members' public and unlisted posts will actually go up public or unlisted. |

## Plan entitlements (current code)
| Feature | Free | $3 Starter | $9 Full |
|---|---|---|---|
| Profile, portfolio, landing page and quote form | Yes | Yes | Yes |
| Customer reviews on the page (respond and flag from the dashboard) | Yes | Yes | Yes |
| Leads | Log in to see them | Plus email alerts | Plus email alerts |
| Daily summary email | — | Yes | Yes |
| Weekly update email | Yes | Daily instead | Daily instead |
| Texts (SMS) | None | 1 a day: the morning rundown | Up to 2 a day: rundown plus one more (new lead or afternoon follow-up) |
| Community, Supplies, Hiring, mentoring, meetups, handoffs, follow-up tracker | Yes | Yes | Yes |
| Pay & rates and cost calculator | Yes | Yes | Yes |
| Part lookup by number | Yes | Yes | Yes |
| AI helper | 3/day, 10/month (when switched on) | Same (no paid allowance decided) | Same (no paid allowance decided) |
| Photo part identification | Off until an allowance and budget are approved | Same | Same |
| Team accounts | Yes | Yes | Yes |
| Break Room, video clips | Yes | Yes | Yes |
| Custom domain (CNAME), Google Business Profile sync, time tracking | Not built in Trade Circle | Advertised, not built | Advertised, not built |
| YouTube auto-posting | No | Yes — connect a channel in Settings, once the site operator has connected the site's Google project | Yes — same |
| Basic invoicing through Empire | Not connected | Not connected | Not connected |

Nothing in this slice changed an existing entitlement. Unresolved: paid-plan AI allowances, a photo part-lookup allowance and budget, whether invoicing becomes free, and whether the $3 description should list only what works today.

## Handoff counting rules (documented)
- **Week:** Monday 12:00 AM to Sunday 11:59 PM in `TC_TIMEZONE` (default America/Chicago). The reset time is shown with its zone, for example "Monday, Oct 26, 12:00 AM CDT".
- **Counts toward the weekly limits:** proposed (pending), accepted and completed handoffs sent outside a vacation.
- **Gives the slot back:** declined by the recipient, or withdrawn by the sender before a reply.
- **Vacation-period handoffs:** don't count, and don't use up the normal allowance afterward.
- **After acceptance (decided Oct 23):** the recipient can hand the job back (reverse) with a reason; the job returns to the sender's sheet as it was, and the sender's slot comes back. The sender can ask to cancel with a reason; the recipient agrees (job returns, the slot stays used) or keeps the job. Completed handoffs can't be reversed or cancelled.
- **Vacations (decided Oct 23):** separate vacations need at least 90 days (about 3 months) between them; an entry that overlaps or directly continues one is the same vacation, up to 14 days.

## Earlier supporting ideas: what exists
| Idea | Status |
|---|---|
| Onboarding checklist | Not built. |
| Available / booked / vacation statuses | Only vacation exists (for handoffs). No public availability status. |
| Why a marketplace lead matches | Not applicable yet: there is no lead marketplace. |
| Alert delivery history | Partly: every alert is stored with its status (queued, sent, failed, expired, opted out). There's no screen for it. |
| Confirmed vs self-reported profile details | Partly: insurance shows "pending review" until an admin checks it, and directory facts are kept apart from opinions. Licenses are self-reported but not labeled that way. |

## Recurring costs
| Service | Cost to Trade Circle |
|---|---|
| Voice dictation | None: the browser's own speech recognition (Apple or Google processes the audio). |
| Maps and distance | None: public Census data stored in the app. |
| Photo storage | Server disk today. Moving to object storage (for example Cloudflare R2) would add a small monthly cost by volume. |
| Text alerts | Twilio, per message plus number fees; paid plans only. |
| Email alerts | Resend, by volume; paid plans only. |
| In-app notifications | None. |
| AI helper and photo part lookup | Provider tokens, capped by the monthly budgets you set; nothing until configured. |
| Video clips | Server CPU for re-encoding (ffmpeg, about the clip's length or less per clip) and disk for storage, roughly 5–15 MB per minute at 720p. Blurring would need a separate service. |
| YouTube music player, 2048 game | None. |

## Next, in order
1. **Tiers and billing**: enforce the free/$3/$9 feature gates; subscription billing.
2. **Stripe Connect payments** (full tier): hosted onboarding, payment page, card or ACH, card on file, partial payments using a ledger with one PaymentIntent per slice.
3. **Invoice tie-in through Empire** (#5), and piping quote requests into Empire.
4. **Scheduling calendar** (#6) and **time tracking** (#8). The calendar should show vacations, handoff dates and meetups.
5. **Crew sharing** (#7).
6. **Google Business Profile sync** (#3) and **custom domains via CNAME**.
7. **Lead marketplace** (#9): 3 bids a month on free, unlimited on full, with compact previews (job type, location, requested date, photos, budget; missing information marked).
8. **Community, remaining**: cheers economy, peer connections by trade and city, opt-in dispute threads.
9. **YouTube auto-post**, portfolio PDF and link export, seasonal quoting tools, job costing templates.
10. **Referrals** with chargeback clawback and payout freeze; **Academy** content pipeline.

## Open questions on handoffs
- **Time zones:** the week and "today" use one platform time zone. Members elsewhere get the reset at the same instant, shown with the zone label. A per-member time zone is a later option.
- **Same job offered twice at once:** a job with an open offer can't be offered again, but two offers sent in the same instant could both go through (each still uses a weekly slot). A database-level guard would close this.
- **Review thresholds:** pairs are flagged at 4 or more handoffs in 12 weeks one way, or 8 both ways combined. These are starting numbers, adjustable per request.

## Open items on photos
- **Cloud storage:** photos are on the server's disk. Back that folder up, or add an object-storage store (for example Cloudflare R2) with the same save/delete/url methods in `backend/app/media.py`.
- **HEIC:** iPhones convert to JPEG when uploading from a browser; a raw HEIC file from elsewhere is refused with a clear message.
- **Insurance certificates** still go in as links; they could use the same upload, kept private rather than public.

## Open items on community features
- **Moderator screens:** reports, removal requests and supplier listings are handled through admin API routes; there's no admin screen yet.
- **Removal confirmation:** done by a moderator by hand (for example, a reply from an email at the business's domain). An automatic email-code check could come later.
- **Anonymization limits:** names, website, addresses and street names are replaced automatically; anything else that identifies the business (nicknames, descriptions) relies on the moderator review that every change triggers.
- **Blocking scope:** blocks stop requests and messages, and hide members from each other's mentoring lists; posts and replies stay visible.
- **Search:** simple text matching; a search index would be needed at larger volume.
- **Seed coverage:** five national chains with no branch addresses; local suppliers come from member suggestions.

## Open items on the competitor-gap additions
- **Not verified live:** the YouTube player loaded in the browser test, kept its place across pages and paused on hide and close, but YouTube refused playback in the cloud test browser; check it on a real phone. AI calls have only been tested against a stand-in provider. Video playback was checked by measuring the published file, not by watching it on a phone.
- **Data-sharing review** before turning on rate comparisons (suppression threshold, 90-day delay, statewide grouping).
- **Paid-plan AI allowances** and **photo part-lookup budget** need decisions; never promise unlimited AI.
- **Giveaways and offers:** none seeded. A moderator adds them from the organizer's page, after checking that its terms allow sharing.
- **Empire invoicing:** the engine exists in Momoempire but isn't deployed or connected to Trade Circle; account linking is the first step (see the investigation).
- **Connecticut ZIPs** show statewide wage figures: BLS uses the state's new planning regions and the Census ZIP file still has the old counties. A town-to-region crosswalk would fix it.
- **Outside estimates** can't be checked automatically against their source; that relies on members reporting and moderators.
- **Usage counts:** daily totals are in `/api/admin/usage`; there's no screen.

## Before production
- Run more than one app worker only after moving the rate-limit counters to a shared store; they are in-process today.
- Give the app's database user `insert` and `find` only on `audit_log`, so the database also enforces append-only.
- Cap request size at the proxy too (for example nginx `client_max_body_size 16m`), so oversized uploads are refused before reaching the app.
- Set `TC_TRUST_PROXY=true` only behind our own proxy, which must overwrite `X-Forwarded-Proto` and append to `X-Forwarded-For`.
