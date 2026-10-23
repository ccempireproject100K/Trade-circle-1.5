# Trade Circle: competitor-gap additions
Recorded October 23, 2026. Adds to [`spec.md`](spec.md) and [`spec-community.md`](spec-community.md); it doesn't replace them. No timelines. Distinguish existing code, planned features and verified working integrations. Don't assume a competitor's advertised feature is live, unlimited or equivalent to ours; keep competitor unknowns labeled unknown.

## 1. Pay and billing-rate comparisons (free)
- Separate views: employee wages (trade, location, role, experience; base pay, overtime, benefits where data supports it) and contractor billing rates (trade, location; labor-only, materials, travel, service-call minimums, hourly versus project).
- Ranges, source, date and sample size where available. Self-reported data labeled. Never invent averages or imply local coverage when data is sparse.
- Individual submissions private. Publish only sufficiently aggregated historical data, suppress small groups, never expose identifiable competitors' current or future prices. Informational, not recommended or coordinated rates. Review the data-sharing design before launch.
- Private cost calculator: overhead, expected billable hours, desired compensation, optional profit. Explain the math; distinguish markup from margin. Inputs never shared.

## 2. Employment listings (only if missing)
Check jobs, marketplace and crew sharing first. If needed: a clearly labeled employment category (company openings, trade and location filters, job details, applications or contact instructions), distinct from customer projects, leads and handoffs. Reuse search, moderation and messaging.

## 3. Photo-based part identification and supplier lookup
- Photo or model/part number; read visible labels; suggest possible matches; ask for more detail when uncertain; contractor confirms; link to supplier product pages or prepare an availability inquiry.
- Possible visual match versus exact model match kept distinct. No compatibility, price or stock inferred from appearance. Sources shown; availability unconfirmed unless current supplier data supports it.
- Live inventory, multi-supplier quoting and ordering are later extensions needing supplier integrations.
- Photo analysis: separate configurable usage limits and spending budget; never unlimited in free access. Paid image analysis stays disabled until its allowance and costs are approved; manual part-number search works meanwhile.

## 4. Contractor-facing AI helper
- Separate from the customer-facing lead-capture assistant. Trade questions, material research, help using the site. Uncertainty clear; authoritative sources cited for technical claims where available; never presented as certification or a substitute for codes and qualified judgment.
- Free allowance: up to 3 successful answers per day and 10 per calendar month; both apply. Failed requests don't use the member's allowance, but provider cost still counts against platform spending.
- Show remaining allowance and exact reset dates; document the time zone; limits configurable. Backend enforcement including concurrent requests. Bounded input, output, history, tool calls and retries.
- Shared AI spending ceiling: reserve the maximum request cost before calling, reconcile actual usage, stop new paid requests when the budget is insufficient. Provider keys server-side.
- No paid AI calls until the model, current pricing and platform budget are configured. Never promise unlimited AI at $3.
- Notices: individual cap "Your free AI questions refresh on [date]."; shared budget "Community AI is temporarily unavailable. Please try again [confirmed reset time]." (omit the time when unknown). Never blame a community limit when only one member is out.

## 5. Optional company accounts
Extend business profiles. Owner invites members as admins or contributors with separate logins and explicit permissions; invitation acceptance, access removal, records of important changes. Ownership and billing protected; contributors can't raise their own access; revoking stops later actions. Employees linking personal profiles to a business need consent. Solo contractors need no team setup.

## 6. Break Room giveaways
Inside the Break Room. List existing sponsor-run giveaways: official organizer and entry link, prize, eligibility and geography, closing date and official rules, last-checked date. Check sharing terms. Auto-expire; report broken or suspicious offers. The organizer runs entries, winners and prizes. Never collect or pass on member emails, promise prizes, or imply sponsorship without an agreement. No assumed membership threshold.

## 7. Empire invoicing and free access
- Direction: basic invoicing free through the existing Empire engine; no second invoicing system.
- First confirm which Empire app and backend invoice; whether the Trade Circle connection exists and works; account linking and data isolation; estimates, invoices, sending, PDFs or links, status, reminders; online payments and their fees.
- The earlier spec put the Empire tie-in in the $9 tier and the roadmap marked it unfinished: findings to recheck, not proof Empire's engine is unbuilt.
- No free invoice allowance yet; competitor counts unconfirmed; no restrictive cap as competitor matching without evidence.
- Document invoice creation, email delivery, reminders, AI help and payment processing separately. Free invoicing never means free payment processing.
- Email: check Empire's actual sender; Trade Circle's Resend code needs configuration and delivery verification; verify the owner's Google Workspace edition, Gmail entitlement, admin access, sender setup and capacity before relying on it; evaluate Workspace sending or SMTP relay against current official limits; account for shared usage; queue and retry without duplicates; honest delivery status; storage capacity isn't sending capacity. Report capacity and cost before recommending an allowance or another paid service.
- Free members still log in to see leads; invoice delivery must not unlock lead alerts.

## 8. Paid-tier value
- $3 Starter: custom domain via CNAME (not free domain registration), Google Business Profile sync, time tracking, YouTube auto-posting, eligible paid lead alerts. Recheck and document which work.
- YouTube auto-posting: upload a project video once and optionally send it to the contractor's connected channel, confirming title, description, visibility and channel. Separate from the music player. Investigate authorization, quota and verification before promising public publishing.
- Keep distinct: member/business profile, project portfolio, customer-facing landing page with quote capture. The landing page and quote form are free (owner confirmed).
- Don't change other $3/$9 entitlements automatically; report how free basic invoicing affects tier descriptions.

## 9. Benefits marketplace (open decision, not approved)
Report any relevant partner integration, costs and eligibility; distinguish free marketplace access from paid insurance, retirement, payroll, financing or other services. Don't enroll members or buy services.

## Supplement: Break Room, music, deals
1. **Existing project videos** in walkthroughs alongside photos, with a spoken or typed explanation. No new footage, customer appearances or testimonials required. Preview before publishing; handle faces, addresses and private details by trimming, blurring or replacing the clip; flag editing that needs extra services or cost.
2. **Music button** ("Play here", "Open in YouTube"): official embedded player for a video or playlist link; starts only on tap; one player kept mounted across internal pages; visible at least 200 × 200 with usable controls; compact and expanded layouts; YouTube controls, branding and ads kept; pauses when closed or hidden, when the site isn't visible, or when recording starts; no background, minimized or locked-screen promise; graceful handling of unavailable videos. No audio extraction or hidden player. Loaded only when opened. Called a YouTube integration, not a partnership.
3. **Break Room games:** a few ready-made browser games explicitly authorized for embedding on a commercial site; licensing, ads, privacy and mobile checked; loaded only when chosen; sound user-controlled and not overlapping the music. A small extra.
4. **Public deals and local places:** a few existing public offers with business and location, official source link, details and restrictions, expiration where published, last-checked date. Labeled "Public offer", never "Sponsored"; no invented offers or implied participation or exclusivity. Expired deals hidden; offers without a published expiration flagged for rechecking. Unobtrusive cards. Location filter.
5. **Suggest a Spot or Deal:** place, location, optional link, short explanation; discussion, reporting, light moderation. Member recommendation, public offer and sponsored placement clearly distinguished.
6. **Later, if demand develops:** more games, vendor-submitted offers with approval, labeled paid sponsorships. Not built now; track basic usage.
