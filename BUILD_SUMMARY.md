# Slice 14 — Front door (root landing page)

**Result:** `GET /` now serves a server-rendered front door (was 404). Built the codebase's way — a Jinja template rendered by the existing pages router with the shared `site.css`, same CSP as the contractor pages. No new stack, no SPA changes, no commits/pushes/deploys.

## Files changed

| File | Change |
|---|---|
| `backend/app/routers/pages.py` | New `GET /` route (`home_page`) + `_plan_cards()` builder and copy constants. Pricing context is rendered from `tiers.py` (`PLANS`, `FEATURES` built-only, `FREE_FEATURES`), so the page can only promise what the plan table says is built. Sets `PAGE_CSP` and `Cache-Control: public, max-age=60`, mirroring `_render`. No DB dependency — works logged out. |
| `backend/app/templates/home.html` | New template extending `base.html`. Header (Trade Circle wordmark + Log in `/app/login`, Sign up `/app/signup`), hero ("The community and work network for contractor small businesses", primary CTA "Create your free page" → `/app/signup`, secondary → `/request`), 9-card feature grid drawn only from built features (page+quote form, portfolio, reviews, handoffs/vacation coverage, marketplace, community/Break Room, pay & rates + cost calculator; Starter-badged: daily rundown, time tracking, YouTube auto-posting; Full-badged: Stripe customer payments), homeowners strip → `/request`, pricing cards with per-plan text policy (Free: weekly update email, no texts; Starter: one rundown text/day; Full: up to two/day), closing "© Mind At Ease Solutions". Meta description + Open Graph (title/description/type/url) in the meta block. |
| `backend/app/static/site.css` | Appended a "front door" section: `.site-header`/`.wordmark`/`.site-nav`, `.feature-grid` (1 col → 2 col at 560px), `.price-grid` (1 col → 3 col at 720px), `.plan`, `.copyright`. Reuses existing `.hero`, `.card`, `.btn`, `.badge`, `.list` and the `--brand` variable (default brand `#1F4E79` passed from the router, same as profile pages). |
| `backend/tests/test_pages.py` | +3 tests: front door renders 200 with hero/pricing/real links and advertises nothing not-built (explicitly asserts no Google Business Profile sync, crew sharing, or Empire invoicing copy) and no `/privacy` or `/terms` links; renders 200 with every integration configured (Twilio, Resend, Stripe, AI, YouTube, Academy, custom public_url); unknown paths and unknown `/p/<slug>` still 404 while a published page and `/health` still answer. |
| `docs/roadmap.md` | Slice 14 — Front door entry added after Slice 13. |

## Decisions worth noting

- **No /privacy or /terms links:** verified no such routes exist anywhere in the backend, so the footer carries only the © line (the shared `base.html` footer already prints "Powered by Trade Circle · Mind At Ease Solutions"). Add the links when the legal pages land (the YouTube verification packet drafts are the source text).
- **Homeowner entry is `/request`** — the existing public, server-rendered marketplace form (GET + POST), not a dashboard route.
- **Route safety:** the pages router is included last in `main.py`; `GET /` collides with nothing (SPA catch-all is `/app/{path}`, mounts are `/static` and `/media`). `/p/<slug>`, `/p/<slug>/full`, `/app`, `/health`, and all `/api` routes verified unchanged by the full suite plus the new regression test.

## Test counts (final, both full suites re-run on this tree)

- Backend: **269 passed** (266 baseline + 3 new), 0 failed.
- Frontend: **89 passed** (unchanged — no SPA files touched).
- Rendered-output spot check: extracted the live pricing section from a test-client render — Free / $3/mo / $9/mo cards list only built features, with the text policy stated per plan.

---

# Slice 15 — Feed-first member home

**Result:** The signed-in home (`/app` index route) is now feed-first, per the owner's concept (2026-10-23): a member lands on the community feed — the same stream the Community page renders — with a prominent My page card and the old work signals demoted to a compact strip. Frontend only; no backend changes, no commits/pushes/deploys.

## Files changed

| File | Change |
|---|---|
| `frontend/src/pages/Home.jsx` | Rebuilt around a `.home-layout` grid. Main column: the feed — `GET /posts` rendered with the shared `PostCard` from `components/Community.jsx` (same cards, same replies links into `/posts/:id`; no second feed implementation), headed by a composer card that reuses the Community page's posting entry (the `/share` chooser) as a prompt plus quick links to the project/lesson/equipment/meetup/opening flows, and a "Community — search & filters →" link for the full page. Side column: **My page** card, work strip, Activity, Coming up, Plan. Empty feed renders a starter card (welcome + Share your first post / Complete your profile / Host a meetup), never a blank column; a feed fetch failure points at the Community page instead of breaking home. |
| `frontend/src/styles.css` | New home section: `.home-layout` grid areas (mobile order: mypage → strip → feed → activity → coming → plan), `.work-strip` (compact `.stat` tiles), `.composer-box` (pill prompt). At ≥900px the layout breaks out of the 760px content column to `min(1080px, 100vw − 32px)` with two columns — feed left, cards right — using the standard centered-breakout technique. The pre-existing `.stats`/`.stat` rules are untouched. |
| `frontend/src/test/home.test.jsx` | **New file — Home had no tests before this slice.** 6 tests: feed renders posts through the shared cards + composer links; empty-feed starter state; My page card links (`/p/<slug>` in a new tab, Edit profile, page URL); hidden-page variant leads with the Profile fix link; work strip counts and links; re-homed Activity / Coming up / handoff banner still render. |
| `frontend/src/auth.jsx` | Test utility only: `AuthStubProvider` accepts an optional `profile` prop (default unchanged) so tests can stub a hidden page. Not used by the app itself. |
| `docs/roadmap.md` | "Slice 15 — Feed-first member home" entry added after Slice 14. |

## How every old Home element was re-homed (nothing dropped)

| Before | Now |
|---|---|
| Stats row (new quote requests, open jobs) | Work strip, plus two more tiles: follow-ups due (from the same `/inbox` data: `follow_up_on` today or past and still open, matching the Inbox overdue rule) and marketplace jobs (`GET /marketplace?radius=30` request count, "Set area" until an area is saved) |
| "Your page" card (URL, View page, Copy link) | **My page** card at the top of the side column (first on mobile), adding an **Edit profile** shortcut; when `published === false` it leads with the hidden notice + "Turn it on in Profile" instead of the URL |
| Activity (notifications) card | Side column, unchanged behavior incl. Mark all read |
| Coming up (next 3 scheduled jobs) | Side column, unchanged |
| Plan card | Side column, unchanged copy |
| Handoff-request banner | Unchanged, still full-width above the layout (it's actionable) |
| Quick links (AI helper, part lookup, rates, Break Room) + greeting | Unchanged, above the layout |

## Decisions worth noting

- **No inline composer was invented:** the Community page has no inline composer — posting runs through the guided `/share` flows — so home reuses that exact entry point rather than forking a second posting path with different rules. Reactions/comments live on the post detail page in the existing design; the shared `PostCard` already links there, so behavior is identical to Community.
- **Follow-ups due** is computed from data Home already loaded (`/inbox`), no new endpoint; the feed needed no backend tweak either (`GET /posts` with no params is the Community "Everything" stream).

## Test counts (final, both full suites re-run on this tree)

- Frontend: **95 passed** (89 baseline + 6 new in `test/home.test.jsx`), 0 failed, 17 files.
- Backend: **269 passed** (unchanged — no backend files touched), 0 failed.


# Slice 16 — Eggshell & green retheme

Owner direction (2026-10-23): the blue platform theme "looks like Facebook" and goes. New brand: eggshell / pastel yellow base, deep friendly green as the partner color, a horizontal stripe motif (green band, thin gold line), friendlier and livelier while staying professional. The three generated cartoon illustrations are light decoration only — miniature, never the dominant element.

## Palette applied (both surfaces)

| Token | Value | Use |
|---|---|---|
| Eggshell | `#FFF9E6` | Page/app background |
| Hero band | `#FCEFB0` | Front-door hero background (charcoal text on it) |
| Card | `#FFFDF5` | Warm off-white cards |
| Border | `#EFE3B0` | Soft card/field borders |
| Text | `#2B2622` | Warm charcoal body text |
| Muted | `#6B6257` | Secondary text |
| Green | `#1E7F46` | Primary buttons, links, accents, platform default brand color |
| Green dark | `#166838` | Primary hover |
| Gold | `#F2C230` | The stripe's thin line |

Dark mode on both surfaces follows the same warm family (deep warm-brown backgrounds, eggshell text, lightened green accent `#4CC37F` / `#3FA95F`) so contrast holds. Green buttons carry white text — confirmed two ways: the SPA's `--accent-text` is white, and `text_color_on("#1E7F46")` computes to `#FFFFFF` (relative luminance ≈ 0.159 < 0.179) for the server-rendered pages.

## Files changed

| File | Change |
|---|---|
| `backend/app/static/site.css` | New `:root` palette (light + dark); `--green` / `--green-dark` / `--gold` / `--hero-band` tokens; `.brand-stripe` class (11px: 8px green over 3px gold); `.home-hero` pastel band with charcoal text; miniature art rules — `.hero-flex` (column on phones, row ≥720px), `.hero-art` 160px phones / 280px desktop, `.feature-art` 112px |
| `backend/app/templates/home.html` | Stripe under the site header; hero restructured into `.hero-flex` (copy + modest art beside the headline) with the stripe flush at the hero's foot; handoff illustration (112px) in the Handoffs & vacation coverage feature; reviews illustration (112px) in the For homeowners card; descriptive alt text on all three |
| `backend/app/routers/pages.py` | New `GET /static/img/{name}.webp` route (router is included before the `/static` mount, so it wins): decodes `static/img/<name>.webp.b64`, serves `image/webp` with `Cache-Control: public, max-age=31536000, immutable`, in-process byte cache, 404 for unknown names |
| `backend/app/static/img/hero.webp.b64` | **New** — base64 of the generated hero illustration (five contractors waving), 1920×1280 |
| `backend/app/static/img/handoff.webp.b64` | **New** — base64 of the **v3** handoff illustration (`media-generation-tc-handoff-v3-*.webp`: handshake kept, brown-skinned contractor restored, two arms per person); verified byte-identical to the source (sha256 match) |
| `backend/app/static/img/reviews.webp.b64` | **New** — base64 of the homeowner five-star-review illustration, 1920×1280 |
| `backend/app/profiles.py` | `DEFAULT_BRAND_COLOR` `#1F4E79` → `#1E7F46`. Contractors' stored custom colors untouched |
| `backend/app/templates/request.html`, `request_status.html` | Hardcoded platform brand `#1F4E79` → `#1E7F46` (brand-text stays white, correct on the green) |
| `frontend/src/styles.css` | Same palette in the SPA variables (`--accent` green, `--accent-dark` hover, eggshell `--bg`, warm card/line/text/muted, dark-mode harmonized); `.brand-stripe` class using the accent + gold; `.topbar-wrap` (header + stripe stick together — the offset for the desktop tab bar moved 46px → 55px); `.btn-primary:hover` dark green; `.auth-art` miniature rule (200px, centered) |
| `frontend/src/components/Shell.jsx` | Header wrapped in `.topbar-wrap` with the `.brand-stripe` div directly under the topbar |
| `frontend/src/pages/Login.jsx`, `frontend/src/pages/Signup.jsx` | Hero illustration as a small (200px) centered panel above the form card, with alt text; forms themselves untouched |
| `frontend/src/pages/Profile.jsx` | Editor default `DEFAULT_COLOR` `#1F4E79` → `#1E7F46`, matching the backend platform default (a stored custom color still wins) |
| `backend/tests/test_pages.py` | 2 new tests: the front door references all three illustration URLs; each serves 200 as a real WebP (RIFF/WEBP magic) with the one-year cache header, and an unknown name 404s |
| `docs/roadmap.md` | "Slice 16 — Eggshell & green retheme" entry added after Slice 15 |

## Decisions worth noting

- **No test pinned the old default.** The only `#1F4E79` left in the tree is a standalone `text_color_on` unit test (test_pages.py) that exercises the luminance function with an arbitrary dark color — it is not a default-color assertion and passed unchanged. Front-door content assertions passed unchanged.
- **Illustrations travel as text.** The Git mirror channel rejects binaries, so the WebPs are base64 (`.b64`, ~33% larger) and decoded by the new route — the same trick keeps them deployable without a binary asset pipeline. StaticFiles also exposes the `.b64` text files under `/static/img/`; harmless.
- **Sizing follows the owner's "light decoration" ruling:** hero art 280px desktop / 160px phones beside the headline (flex row/column), feature spots 112px, auth art 200px. Nothing is full-width; nothing pushes content down a screen.
- **Stripe, one class per surface:** `.brand-stripe` exists in both `site.css` and the SPA `styles.css` (the SPA version keys off `--accent` so it lightens correctly in dark mode), placed under the front-door header, at the front-door hero's foot (flush via the hero's padding), and under the dashboard shell header.

## Test counts (final, both full suites re-run on this tree)

- Backend: **271 passed** (269 baseline + 2 new illustration tests), 0 failed.
- Frontend: **95 passed** (unchanged — no test changes needed), 0 failed, 17 files.
- Production build: `npm run build` succeeds.


# Slice 16 FINAL — Strong yellow, dark brown & wood grain (supersedes the eggshell & green build above)

Owner ruling (2026-10-23, later the same day): the eggshell/green look above "reads soft" for the trades. Of the stronger directions previewed, he picked his own — **strong yellow + dark brown + dark wood grain** — and ordered **green removed altogether**. This section is the final Slice 16; the eggshell & green section above is superseded and kept only as the record of the draft.

## What changed from the superseded draft

| Area | Final |
|---|---|
| Palette | Dark brown `#4A2F1B` (hover `#3A2413`) is the primary for buttons/links/accents; bold work yellow `#FFB800` is the loud accent and the front-door hero band; warm cream `#FAF3E3` background, `#FFFDF6` cards, `#33241A` text, `#77644F` muted, `#E3D3AE` borders. Dark mode follows the same warm brown family (deep brown backgrounds, golden-tan accent `#D9A45B`). Every green value is gone — the old `#1E7F46` / `#166838` / dark-mode `#3FA95F` / `#2E8A4C` / `#4CC37F` are re-mapped to the brown family, and `--ok` is now the dark brown primary (success reads via text/icon, not color). Verified by grep: zero occurrences of those hexes in the shipped CSS/code. |
| Stripe | `.brand-stripe` is now a **dark wood-grain band over a thin gold (`#F2C230`) line**: layered repeating-linear-gradients in dark browns (`#3E2716` / `#4A2F1B` / `#46311E` / `#3A2413`) with darker streak lines and an inset shadow, the grain sized to the top 8px of the 11px band with the gold showing beneath. Same three placements: under the front-door site header, at the hero's foot, under the SPA shell header. |
| Site header | The front-door header itself wears the wood grain (`.wood-grain` in `site.css`) with cream `#FFF3D6` text and work-yellow nav buttons (yellow bg, brown text). The SPA shell header stays simple: cream card background + the wood stripe under it. |
| Artwork | All three illustrations replaced with the owner's green-free redraws (maroon/gold/charcoal/denim/brown; handshake and the brown-skinned contractor kept in the handoff scene). Same base64 mechanism and `/static/img/{name}.webp` route; each re-encoded file verified **byte-identical to its source asset by sha256** (hero `c9315501…`, handoff `ff0d0390…`, reviews `ac824c5d…`). |
| Hero | The crew picture is now a **faded backdrop inside the hero band**: `.hero-backdrop`, absolutely positioned across the whole bold-yellow hero at 22% opacity, behind the headline and both CTAs ("Create your free page", "Post a job"); the copy layer (`.hero-copy`) sits above it with solid contrast. The old side-by-side `.hero-flex` / `.hero-art` placement is removed. The handoff/reviews feature spots stay 112px miniatures; the login/signup crew panel is unchanged (it serves the same swapped hero art). |
| Tagline | Front-door `<title>` is now "Trade Circle — the community and work network for contractors and small businesses alike" and the `<h1>` reads "The community and work network for contractors and small businesses alike" (owner's exact words). `HOME_DESCRIPTION` (meta/OG) updated to match. |
| Brand default | `DEFAULT_BRAND_COLOR` → `#4A2F1B` in `profiles.py`, the two marketplace templates (`request.html`, `request_status.html`), and the SPA editor's `DEFAULT_COLOR` in `Profile.jsx`. `text_color_on("#4A2F1B")` computes to white, so brand text stays correct. Contractors' stored custom colors untouched. |

## Tests

- `backend/tests/test_pages.py`: the front-door test's title/headline assertions updated to the final tagline; two tests added — the illustration routes serve bytes identical to the encoded `.b64` artwork, and the home page carries the final tagline in `<title>` + `<h1>` with the hero in backdrop form (no side-by-side `.hero-art`).
- Full suites re-run on this tree at the end of the build; counts recorded in the parent handoff.


## Owner adjustments (2026-10-23, after the Slice 16 FINAL build)

Four follow-ups from the owner's look at the finished front door, applied to the same tree. No commits, pushes, or deploys — the parent verifies and presents.

| # | Adjustment | What changed |
|---|---|---|
| 1 | Hero art swap | `backend/app/static/img/hero.webp.b64` now encodes the mom-and-pop storefront scene (crew of five in front of the shop, sign "MOM & POP'S", green-free). Same base64 mechanism and `/static/img/hero.webp` route; verified byte-identical to the source asset by sha256 (`66714d01813b49254077798c3edb1f324464cac36fcd522e5338c40b23766d1b`). The hero backdrop `<img>` alt text now describes the shop scene. Handoff/reviews assets unchanged. |
| 2 | Per-plan text copy | `_TEXT_POLICY` in `routers/pages.py`: Free → "No texts — a weekly update by email.", Starter → "You get one text a day.", Full → "You get two texts a day." Each card states only its own allowance. The cross-referencing `daily_summary` label in `tiers.py` ("…(1 text a day on Starter, up to 2 on Full)" — it rendered inside the Starter card and the in-app Plan catalog) is now "Daily email summary, and the morning rundown as a text". The per-member Settings policy (`routers/alerts.py` `SMS_POLICY`) already describes only the member's own plan and was left as-is. |
| 3 | Uniform tier groups | `home.html` "What you get" restructured into three headed groups in plan order — "On every free page" (public page, handoffs & vacation coverage, lead marketplace, community & break room, pay & rates + cost calculator), "Starter adds" (daily rundown, time tracking, YouTube auto-posting), "Full adds" (customer payments) — every feature exactly once, feature copy intact, and the scattered inline `<span class="badge">Starter/Full</span>` labels removed (the group heading carries the tier). A small `.feature-group` heading style was added to `site.css`. Pricing cards keep their tiers.py-generated points (each feature is claimed only at its own tier, consistent with the groups). |
| 4 | New businesses + Starting Out lane | New compact "Just starting out?" card between "For homeowners" and pricing (free page as first storefront, marketplace bids incl. the free plan's 3/month, community mentoring, pay & rates + cost calculator for first pricing, overflow handoffs; CTA "Create your free page" → `/app/signup`). To make the mentoring/meetup copy concretely true, a dedicated community post kind **`starting_out`** was added through the existing machinery: `Kind.starting_out` + `NoFields` in `backend/app/community.py` (publishes on post like the other simple kinds, appears in `/api/community/meta` and the `?kind=` feed filter), `KIND_NAMES` in `frontend/src/labels.js`, a "Starting Out" filter chip in `pages/Community.jsx`, a `ShareStartingOut` form in `pages/ShareForms.jsx` routed in `pages/ShareRouter.jsx`, and a Share chooser entry in `pages/Share.jsx`. The front-door section names the lane. |

## Tests (full pass, this tree)

- Backend: **276 passed** (273 Slice 16 FINAL baseline + 3 new: front-door tier-grouping/per-card texts test, new-businesses section test, Starting Out post create/filter/meta test in `test_community.py`). Front-door assertions updated for the new texts lines and the badge removal.
- Frontend: **95 passed** (unchanged count — no test changes needed), and `npm run build` succeeds.
