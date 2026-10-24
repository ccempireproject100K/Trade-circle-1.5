# Trade Circle spec
Version 1 — recorded October 23, 2026, from Brandon's dictated spec. Moved here from `empire-project/docs/trade-circle-spec.md`.
Product of Mind At Ease Solutions. Host: `tradecircle.mindateasesolutions.com` (the live Mind At Ease domain is `mindateasesolutions.com`; the dictation said `mindatease.com`).
This is a spec, not a build record. Nothing below is implemented, launched or priced live yet.

## Power features
| # | Feature | Notes |
|---|---|---|
| 1 | Photo portfolio | Simple upload flow, simpler than YouTube's. Export as PDF or shareable link. |
| 2 | Landing page | Scannable first layer of the two-layer profile. |
| 3 | Google Business Profile sync | Starter tier and up. |
| 4 | Job sheet | Free tier. |
| 5 | Invoice tie-in through Empire | Full tier. |
| 6 | Scheduling calendar | Free tier gets a basic view. |
| 7 | Crew sharing | Full tier. |
| 8 | Time tracking | Starter tier and up. |
| 9 | Lead marketplace | Free: 3 bids per month. Full: unlimited. |

## Supporting layer
- **Cheers economy** with in-and-out reciprocity.
- **Peer connections** gated by trade and city.
- **Unverified profiles** allowed, with visible lapsed-cert badges.
- **Re-certification celebration banners** that run 2–3 days.
- **Profile customization** by drag and drop, with auto-reflow.
- **Two-layer profiles:** scannable landing page plus a deep full profile.
- **Request-a-quote button** piping into Empire.
- **Dispute threads**, opt-in only.
- **YouTube auto-posting.** Cross-posting goes to YouTube only. No TikTok. No live rooms.
- **Academy link** sits in the footer, not promoted elsewhere.
- **Call buttons on profiles:** `tel:` link for calls, FaceTime button shown on Apple devices.
- **Portfolio export** as PDF or shareable link.
- **Seasonal quoting tools.**
- **Job costing templates.**
- **Insurance verification** with visible status badges.

## Job handoffs
Added October 23, 2026. Trade Circle is for networking, community and brand building. Handoffs let members occasionally get existing commitments covered, without encouraging overbooking, job brokering or exclusive handoff partnerships.

1. **Normal limits:** up to 3 outgoing handoffs per week in total, no more than 2 to the same member. The limits are explained before a member sends one.
2. **At the limit:** more outgoing handoffs are blocked for the rest of the week. Everything else keeps working. The member is told when the allowance resets and that they can arrange extra coverage outside the platform.
3. **Vacation exception:** tied to the member's vacation setting, with a start date, an end date and a short note. A vacation lasts at most 14 consecutive days. During it, the normal outgoing limits are lifted.
4. **After vacation:** normal limits come back automatically when it ends. Coverage beyond 14 days is arranged outside the platform. Overlapping or back-to-back vacation entries can't extend the exception beyond 14 days.
5. **Transparency:** the recipient sees the proposed job and accepts or declines. Sender, recipient, dates, acceptance and completion are recorded. A proposal isn't accepted until the recipient confirms.
6. **Community safeguards:** no permanent "handoff partner" feature and no preferential access for groups. A reviewable history of repeated exchanges lets unusual patterns be assessed, without automatic penalties.

## Pricing
| Tier | Price | Includes |
|---|---|---|
| Free | $0 | Page, photo portfolio, clips, job sheet, community access, basic scheduling view, 3 lead marketplace bids per month, quote button that captures leads into the Trade Circle inbox |
| Starter | $3 | Everything in Free, plus a portable page (yours to keep, host anywhere under your own domain — Trade Circle never gives or hosts domains), Google Business Profile sync, time tracking, YouTube auto-post |
| Full | $9 | Everything in Starter, plus invoicing through Empire, crew sharing, voice onboarding, priority support, monthly profile and Google listing performance report, unlimited lead marketplace, Stripe Connect payments (card-on-file toggle, ACH option, partial payments, save card for next invoice) |

New-lead alerts are a paid-plan feature: email alerts on both paid plans, and texts capped by plan,
counted on the platform's calendar day — Starter gets 1 text a day (the morning rundown), Full gets
up to 2 a day (the rundown plus one more: a new-lead text or the afternoon follow-up reminder,
whichever comes first). Emails are not capped. Free-plan contractors log in to see their leads, and
get one weekly update email (Monday morning, only when there's something new).

Billing period is not stated in the dictation; assumed monthly until confirmed.

## Payments
- **Stripe Connect.** Contractors link their own Stripe account through Stripe-hosted onboarding.
- Money flows direct to the contractor's bank. The platform never touches funds.
- Stripe fees land on the contractor. Rates as dictated: 2.99% cards, 1% ACH, 3.5% keyed-in. Confirm against current Stripe pricing before publishing.

### Payment page
- Mobile-first.
- Large amount display and a big **Pay Now** button.
- Contractor brand colors.
- One-line personal note from the contractor.
- Card or ACH choice at checkout.
- Card-on-file toggle; save card for the next invoice.

### Partial payments
- Running balance stored in a backend ledger.
- One PaymentIntent per payment slice.

## Security
- Passwords hashed with bcrypt or argon2.
- HTTPS everywhere.
- Rate limiting on login and quote endpoints.
- Role-based access. Contractors see only their own data.
- Audit logging via middleware on all sensitive routes, written to a separate append-only table: user ID, timestamp, action, affected record.
- No card data stored. Stripe handles PCI.
- Reuse Empire security module patterns.

## Audio and video specs
### Narration
- AI voice narration.
- Short sentences, max 15 words per beat.
- Strong pauses with ellipses; vary pause lengths.
- Beats clustered in groups of 4–5 lines, with breath breaks between clusters.
- An "Are you ready?" prompt before action steps, then "Here we go" after a beat.
- In-clip questions for engagement, and mini self-audits.

### Music and cues
- Bed music under −18 dB.
- Three rotating beds:

| Modules | Bed | Chime before action steps |
|---|---|---|
| 1–5 | Soft piano | Low C |
| 6–10 | Ambient pads | E |
| 11–15 | Gentle acoustic guitar | G |

## Referral system
The existing Mind At Ease referral plan applies.
- Referrer earns 25% of each referred paying customer's revenue for 6 months.
- Only current customers in good standing can refer.
- Payout only on net revenue, after disputes and refunds clear.
- **Chargeback:** if a referred payment is charged back, the referrer's payout for that month is clawed back and future payouts freeze until the dispute resolves.
- **Review trigger:** 3 chargebacks in 6 months triggers manual review.
- **Refunds:** excluded from payout revenue.

## Academy
### Modules (15)
| # | Track | Topic |
|---|---|---|
| 1 | Numbers | P&L |
| 2 | Numbers | Job costing |
| 3 | Numbers | Cash flow |
| 4 | Numbers | Overhead rate |
| 5 | Numbers | Taxes |
| 6 | Business | Leads |
| 7 | Business | Estimates |
| 8 | Business | Pricing |
| 9 | Business | Insurance |
| 10 | Business | Crew decisions |
| 11 | Business | Invoicing |
| 12 | Business | LLC structure |
| 13 | Business | Contracts |
| 14 | Business | Tools |
| 15 | Business | Scaling to first office hire |

### Content rules
- Free sample lesson per module, with rotating topics.
- Samples stop before actionable depth and point to free public resources.
- AI voice scripts, following the narration spec above.
- Visual clips run 60–90 seconds.

### Production
- About 70% built from stock animation templates (Canva and Envato).
- Custom builds for trade-specific visuals.
- The Academy lives on the Mind At Ease site (Momoempire repo). Trade Circle links to it.
- Canva connected for prototyping. A Grok bot on the cloud box drives Canva via its API.
- Specs are versioned as markdown in this repo (`docs/`).

## Open questions
- Confirm tier prices are monthly.
- Confirm Stripe fee figures; Stripe's published card rate is usually stated as a percentage plus a fixed per-transaction fee.
