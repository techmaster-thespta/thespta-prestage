# Thunder Hill Elementary PTA Website

This repo is a static-site generator: `config/*.json` (data) +
`src/templates/*.tmpl` (structure) → `python3 src/build.py` →
`/pages/*.html`. GitHub Actions builds and deploys those pages straight
to **GitHub Pages**, served at the custom domain in `config/site.json`'s
`custom_domain` field (currently `www.thespta.org`) via a generated
`CNAME` file — self-hosted, no Google Sites embedding. A content change
is just a config edit + push.

**Staging**: `techmaster-thespta/thespta-prestage` is a separate repo
that mirrors this one for previewing changes before they hit production,
live at `https://techmaster-thespta.github.io/thespta-prestage/`. See
the `rebuild-now` skill's pattern for pushing this repo's current branch
there and redeploying.

## The one rule that matters most

**Content changes are config-only. Do not edit `src/` unless the user
explicitly asks for a structural or design change.**

Every routine addition (a board member, sponsor, flyer) has a matching
skill in `.claude/skills/` — use it. Those skills are deliberately scoped
to touching only `config/*.json`, because:

- `src/templates/` defines the visual system (the "thes" design language:
  navy/blue/yellow/teal/coral, Montserrat + Lato, card/grid patterns).
  Changing it changes the whole site's look, not just one piece of content.
- `src/build.py` is the assembly logic. It's had several rounds of
  deliberate simplification after real mobile-rendering bugs — see
  "Hard-won constraints" below before touching it.
- Config files are safe to edit freely: worst case, re-run the build and
  the site looks the same as before, or a section quietly doesn't render
  (sponsors/flyers with an empty list produce no section at all — this is
  intentional, not a bug).

**Events are the one exception to "config-only"**: they're synced
automatically from Google Calendar by `scripts/sync_calendar_events.py`
(GitHub Actions runs it hourly via `.github/workflows/sync-events.yml`,
and again on every push via `deploy.yml`) — `config/events.json` is
*generated*, like `pages/*.html`, never hand-edited. See
`.claude/skills/add-event/` and `docs/SOP.md` Task 4.

The **nav menu** is also config, not template: `config/site.json`'s
`nav` list drives the header — see "Adding a page to the nav" below.

If a task genuinely needs a template/build.py change (a new page, a new
section type nothing existing covers), say so explicitly and explain why a
config-only approach can't do it, rather than silently editing `src/`.

## Hard-won constraints (don't reintroduce these mistakes)

- **No page can omit the header — it's structural, not a template
  convention.** `build.py`'s `main()` inserts the header right after
  `<div class="thes">` opens, for every page, unconditionally — no page
  template includes a `{{HEADER}}` marker to remember. This exists
  because a real page (the newsletter page) shipped without a header
  once: it was written before this repo had a header concept, and a
  later merge didn't retroactively add a marker nothing enforced.
  Don't reintroduce a marker-based header; if the header needs to change,
  edit `src/templates/header.html.tmpl` or `build_header()`.
- **Every generated page needs its own `<!DOCTYPE html>`/`<head>`/viewport
  meta — these pages are opened directly, not embedded inside another
  page that supplies one.** `build.py`'s `main()` wraps every page in a
  real document shell for exactly this reason. Skipping the viewport meta
  specifically silently breaks every `@media` query meant for phones —
  without it, mobile browsers assume a fake ~980px desktop-width layout
  viewport regardless of the device's real width. This already caused a
  real bug (the mobile hamburger menu never triggered on an actual phone)
  before the fix.
- **The header/nav is the site's one piece of JS-driven UI** — the
  hamburger button and each dropdown nav item's caret are real
  `<button>`s that toggle a plain `.is-open` class via
  `addEventListener` (see the `<script>` in `header.html.tmpl`, appended
  right after the header markup by `build_header()` so it ships on every
  page the same way the header itself does). This replaced an earlier
  pure-CSS checkbox-hack version after that version shipped a real bug:
  a touch tap on a parent nav link (e.g. "Get Involved") could trigger
  `:focus-within` and pop its submenu open with no way to distinguish
  that from a deliberate caret tap, and a user reported the submenu
  showing "from the beginning" with the caret doing nothing. There's no
  framework/bundler anywhere on this site — any other interactive UI is
  plain inline `<script>` in the relevant template, following this same
  pattern. The other real example: the PTA Newsletter page
  (`src/templates/pages/newsletter/pta-newsletter.html.tmpl`) fetches
  its content client-side from Givebacks' newsletter API by id
  (`config/site.json`'s `pta_newsletter_id`) and injects it via
  `srcdoc` on a same-page `<iframe>`, since that newsletter isn't a
  fixed URL this site can just embed directly the way the Smore-hosted
  THES Happenings newsletter is.
- **Mobile-safety**: every grid uses `auto-fit`/`minmax(...)`, never a
  fixed multi-breakpoint layout. Avoid `position: absolute` outside the
  four already-vetted uses (the header dropdown submenu, the page-header
  fade overlay, the calendar iframe's aspect-ratio box, the Home page
  welcome video's aspect-ratio box — same technique as the calendar
  embed, just at true 16:9). Avoid fixed pixel widths on containers.
  A from-scratch redesign broke on mobile once
  already from ignoring this.
- **Images live in `assets/images/` and are served directly by GitHub
  Pages** (`config/site.json` → `hero_image_filename` /
  `page_header_image_filename`, resolved to a relative `images/<file>`
  URL by `src/build.py`). This replaced an earlier Google-Drive-hosted
  approach — don't reintroduce Drive for images or page hosting. A
  service-account-based Drive push was tried and abandoned: service
  accounts have zero storage quota on a plain Gmail "My Drive," so every
  upload failed with `storageQuotaExceeded` regardless of folder sharing.
  An OAuth-as-the-user variant was made to work, but GitHub Pages is
  simpler and was chosen instead — don't re-add either Drive approach.
  The same lesson repeated later with a different feature: afterschool-
  program and fundraiser flyers were briefly Drive-hosted too (a shared
  folder read via the Drive API), until the account that owned the
  folder got flagged by Google and every file in it — even ones on a
  plain public link — started returning "you can't access this item, it
  violates our Terms of Service." Those flyers now live in
  `assets/flyers/before-after-school/` and `assets/flyers/fundraising/`
  in this repo instead — don't reintroduce Drive for these either.
- **`page_urls.*` in `config/site.json` are the only correct way to link
  between pages** — each value is a *slug* (e.g. `"get-involved"`, or
  `"get-involved/committees"` for a nested page), not a full URL.
  `src/build.py` appends `.html` and, for a page that itself lives below
  the site root, prefixes the right number of `../` so the link still
  resolves correctly from that depth (see "Nested pages" below). Never
  hardcode an absolute path (`/events.html`) or a full URL into
  `page_urls.*` — an absolute path breaks the moment a site is served
  from a URL subpath instead of a domain root, which is exactly how the
  `thespta-prestage` staging repo is hosted
  (`techmaster-thespta.github.io/thespta-prestage/`).
- **Nested pages (a page below the site root, e.g.
  `pages/get-involved/committees.html`) need relative links built with
  the right `../` depth — this is what `build_context(depth)` in
  `build.py` is for.** `main()` discovers page templates recursively
  (`(TEMPLATES / "pages").rglob("*.html.tmpl")`), computes each one's
  `depth` from how many directories deep it lives under
  `src/templates/pages/`, and calls `build_context(depth)` (memoized per
  depth, since header/footer/nav links depend on it but content like
  board/event/committee cards don't) — that's what prefixes every
  `page_urls.*` value and the hero/page-header image URLs with the right
  number of `"../"`. If you add another nested page, it gets this for
  free just by living in a subdirectory of `src/templates/pages/`; you
  don't need to touch `build_context` or `main()`. This was built
  because root-absolute paths (`/get-involved.html`) would have been
  simpler but silently broken on the staging repo's subpath hosting —
  relative paths work at both.
  Two real bugs already got caught by this depth change and are worth
  knowing about if you touch page discovery or deployment again:
  `test/validate_build.py` used to glob `pages/*.html` (flat) and would
  silently skip any nested page during validation; and
  `deploy.yml`/`sync-events.yml`'s "Assemble the deployed site" step used
  to `cp pages/*.html site/` (also flat), which would have silently
  **failed to deploy** a nested page even though it built and validated
  fine locally. Both are now recursive (`glob(..., recursive=True)` and
  `cp -r pages/. site/` respectively) — if you ever see a nested page
  validate locally but 404 live, a flat glob/cp regression is the first
  thing to check.
- **Any new colored link/button variant must combine classes, not rely on
  a single one for color** — `.thes a { color: inherit; }` in
  `tokens.html.tmpl` has specificity (0,1,1), which beats a single-class
  selector like `.thes__btn--green { color: ... }` (0,1,0) regardless of
  source order. This exact bug shipped once already: `.thes__btn--navy`
  buttons rendered near-black inherited text instead of white. The fix in
  place is `.thes__btn.thes__btn--navy { ... }` (two classes, specificity
  0,2,0) — follow that pattern for any new button/link color rule.
- **A GitHub-Actions-bot push never triggers another workflow's `push`
  trigger** — this is deliberate loop-prevention baked into `GITHUB_TOKEN`
  (see [GitHub's docs](https://docs.github.com/en/actions/concepts/security/github_token)),
  not a bug to work around with a PAT. This is why
  `.github/workflows/sync-events.yml` does its own full build+validate+deploy
  instead of just committing `config/events.json` and counting on
  `deploy.yml`'s push trigger to pick it up — that handoff would silently
  never fire. Keep this in mind before adding any other bot-committing
  workflow that's meant to cascade into another one.
- **`config/site.json`'s `custom_domain` generates the `CNAME` file
  GitHub Pages needs for the custom domain to work** — `build.py` writes
  `pages/CNAME` from it, and `deploy.yml`/`sync-events.yml` both copy that
  into the deployed `site/`. If the domain ever changes, update
  `custom_domain` and the DNS record pointing at GitHub Pages — don't
  hand-maintain a separate CNAME file, it'll drift.

## Commands

```bash
python3 src/build.py            # regenerate /pages from /config
python3 test/validate_build.py  # validate the output (also runs in CI)
scripts/build.sh                # same as the first command, path-independent
```

## Adding a page to the nav

Edit `config/site.json`'s `nav` list — each item is
`{"label": "...", "page_url": "<a page_urls.* key>"}`. Any item can carry
a `"children": [...]` list (same shape) to become a dropdown/subpage menu
— desktop shows it on hover, mobile lists it indented inside the already-
open mobile menu. This is data, not a template change: adding a subpage
never requires touching `header.html.tmpl` or `build.py`.

## Where things are documented

- `docs/SOP.md` — day-to-day content-editing tasks (the thing to read first for "how do I change X")
- `docs/github-pages-setup.md` — one-time: turning on GitHub Pages and the custom domain for this repo
- `.claude/skills/` — one skill per addable content type (`add-event`,
  `add-board-member`, `add-sponsor`, `add-flyer`, `add-committee`,
  `add-afterschool-program`, `add-pta-meeting`,
  `add-family-support-resource`), the GitHub issue
  workflow (`create-issue` to plan a change and file it, `from-issue` to
  pull an issue by number, implement it, open a PR), `rebuild-now`
  (push pending changes + force an immediate rebuild/redeploy, for
  last-minute changes the user wants live right away rather than waiting
  on the hourly sync or normal push pipeline), and `release` (verify
  `main`, bump `VERSION`, write a board-friendly `CHANGELOG.md` entry,
  cut a tagged GitHub Release — only when the user actually asks for one,
  not automatically on every change).
- `VERSION` / `CHANGELOG.md` — the site's version number and a
  plain-language changelog meant to be shared with the PTA board, not
  just developers. Both only ever move together, via the `release` skill
  — don't hand-edit either mid-change.
- `scripts/sync_calendar_events.py` — generates `config/events.json` from
  the public Google Calendar `.ics` feed (stdlib-only RRULE expansion, no
  API key), including any file attached to an event (rendered as a
  clickable photo preview — confirmed empirically that Google's public
  feed includes `ATTACH` properties) and a "Sign Up" button for any event
  whose Description mentions "sign up" near a URL — natural phrasing,
  not a strict format (confirmed against a real event whose actual text
  was free-form prose, not a dedicated line). Calendar has no dedicated
  field for this the way it does for attachments, so `extract_signup_href`
  just finds the URL and removes it from the description shown on the
  site, leaving the surrounding sentence in place. A `meet.google.com`
  link anywhere in the Description becomes a yellow "Join Google Meet"
  button the same way (`extract_meet_href`) — no keyword needed there,
  the domain alone is the signal. Also generates
  `config/pta-meeting-occurrences.json` — a *separate* pass over the same
  parsed calendar (not a filter over `config/events.json`), every
  upcoming occurrence whose title mentions "PTA" and "meeting", for the
  PTA Meetings page's "Upcoming" section. It has to be separate: `events.json`
  is capped at `MAX_EVENTS` (6) across every event type for the
  Home/Events highlights, so a PTA meeting further out than the 6th
  nearest calendar-wide event would never reach a plain filter over
  `events.json` — this happened for real (a real Feb 2027 meeting was
  invisible on the page despite being well within the general lookahead
  window). It also gets its own longer lookahead
  (`PTA_MEETING_LOOKAHEAD_DAYS`, 400 days vs. the general 180) since
  meetings are roughly monthly but skip summer, so "the next 3" can sit
  further out than the general highlights window. Run by
  `.github/workflows/sync-events.yml` (hourly) and by `deploy.yml` (every
  push/manual run). See `docs/SOP.md` Task 4.
- `scripts/sync_hcpss_calendar.py` — a second, independent calendar
  sync, for a completely different calendar owned by Howard County
  Public School System (not the PTA): the Special Education Parent &
  Guardian Calendar shown on the Special Education & Family Support
  page. Writes `config/hcpss-family-events.json` (the next 3
  occurrences, for that page's "Upcoming Events" list above its live
  calendar embed) by reusing `sync_calendar_events.py`'s generic
  ICS-parsing functions directly (`import`ed — none of that parsing is
  actually PTA-specific) rather than duplicating them, with its own
  calendar id and event cap. One real wrinkle handled here and nowhere
  else: HCPSS's calendar Descriptions contain literal embedded HTML
  (`<span>`/`<p>` tags) — confirmed empirically — unlike the PTA's own
  plain-text ones, so this script strips tags down to plain text before
  handing descriptions off to the shared `build_events_json`, since
  `render_event_description` in `src/build.py` inserts a Description
  unescaped. Run by the same two workflows as `sync_calendar_events.py`,
  right alongside it.
- `scripts/sync_afterschool_flyers.py` / `scripts/sync_fundraiser_flyers.py`
  — reconcile `config/afterschool-programs.json` /
  `config/fundraisers.json` against whatever's actually in
  `assets/flyers/before-after-school/` / `assets/flyers/fundraising/`:
  removes (or, for a fundraiser with real content, detaches) an entry
  whose flyer disappeared, adds a `needs_review` placeholder for a new
  one, flags a changed one. These flyers used to be a shared Google
  Drive folder read via the Drive API (needing a `GOOGLE_DRIVE_API_KEY`
  secret); migrated into the repo after the account that owned the
  folder got flagged by Google and every file in it — even ones on a
  plain public link — started returning "you can't access this item, it
  violates our Terms of Service." Being plain files in the repo means
  the sync can run as a step in `.github/workflows/deploy.yml` on every
  push instead of polling on a schedule — see "Hard-won constraints"
  below. Neither script can write a flyer's actual details
  (name/schedule/price, or for a fundraiser, telling a reprint of an
  existing campaign apart from a genuinely new one) — that's a
  vision/understanding step for a human or an agent, done via
  `.claude/skills/add-afterschool-program/` /
  `.claude/skills/add-fundraiser/` and their matching `review-*` skills.
- `docs/github-agent-setup.md` — GitHub access setup for agents: `gh` CLI
  (shell-capable agents) or the GitHub MCP server declared in `.mcp.json`
  (any MCP-compatible agent). Use whichever this session actually has —
  the skills describe `gh` commands as the reference implementation; an
  MCP-only agent should translate the same intent into MCP tool calls.
- **SEO / AI-assistant discoverability** — `src/build.py`'s `main()`
  generates, per page: a `<meta name="description">` from the
  `PAGE_DESCRIPTIONS` dict (add an entry there for any new page — falls
  back to the Home page's description if missing, rather than shipping
  no description, but a real one is better), a `<link rel="canonical">`
  and `sitemap.xml` entry built from `config/site.json`'s
  `custom_domain`, and one shared `Organization` JSON-LD block
  (`build_organization_jsonld`) built from `site.json`'s
  name/address/email/social fields — this is what lets Google's
  Knowledge Graph (and an AI assistant grounding an answer in search
  results) resolve "Thunder Hill Elementary PTA" as a real, addressable
  entity rather than just prose on a page. `robots.txt` explicitly
  allows the wildcard plus several AI crawlers by name (GPTBot,
  ClaudeBot, anthropic-ai, Google-Extended, PerplexityBot, CCBot) —
  redundant with the wildcard `Allow: /`, but makes the intent to be
  crawled by them legible at a glance. **This output is always the real,
  production version, even when built inside the `thespta-prestage`
  staging repo** — `src/build.py` has no notion of which repo it's
  running in. What actually keeps staging out of search results is a
  step in `deploy.yml`/`sync-events.yml` gated on GitHub Actions' own
  `github.repository` context (`== 'techmaster-thespta/thespta-prestage'`),
  which overwrites `robots.txt` with a blanket disallow and stamps a
  `noindex` meta tag onto every page right before deploying — see the
  "Staging" note at the top of this file and the comment on that step.
  Don't try to make `src/build.py` itself repo-aware instead; the
  workflow-level gate is what actually runs differently per repo despite
  every other file being pushed identically to both.

## Adding a new modular content type

Sponsors and flyers (`config/sponsors.json`, `config/flyers.json`) are the
reference pattern for "a list of things that may be empty." If asked to add
another one (e.g. a photo gallery, a testimonials section):

1. Add `config/<name>.json` defaulting to `[]`.
2. Add `src/templates/card-<name>.html.tmpl` (one item).
3. Add `src/templates/<name>-section.html.tmpl` (the section wrapper, taking a `{{<NAME>_CARDS}}` marker).
4. Wire it into `build_optional_section(...)` in `src/build.py` and add the `{{<NAME>_SECTION}}` marker to whichever page template it belongs on.
5. Confirm an empty config produces no section (not an empty heading) — this is the pattern's whole point.
6. Add a matching skill under `.claude/skills/add-<name>/SKILL.md`.

This is itself a `src/` change — get explicit user sign-off before doing it,
per the rule above.
