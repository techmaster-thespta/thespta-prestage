# Thunder Hill PTA Website — Standard Operating Procedures

This is the reference doc for **ongoing content edits** — written so a
future board member with no coding background can follow it. For the
one-time initial setup, see `docs/github-pages-setup.md` (GitHub Pages +
the custom domain).

The site is fully self-hosted on **GitHub Pages** at the custom domain
`www.thespta.org` — no Google Sites in the chain anymore. A content
change is just: edit a config file, push, done.

## How the system fits together

```
Google Calendar         ← the PTA's shared calendar (events only — see Task 4)
        ↓  scripts/sync_calendar_events.py (GitHub Actions runs this hourly via sync-events.yml, + on every push via deploy.yml)
config/events.json      ← generated — don't hand-edit
config/*.json           ← everything else you DO edit (colors, text, board, sponsors, flyers, nav)
src/templates/*.tmpl    ← page structure (rarely touched)
        ↓  python3 src/build.py   (or: scripts/build.sh)
pages/*.html            ← generated output (including pages/CNAME for the custom domain)
        ↓  git push → GitHub Actions
https://www.thespta.org/*.html   ← the live site
```

**Golden rule: never hand-edit a file in `/pages` or `config/events.json`.**
Both get silently overwritten the next time anyone runs the build/sync —
including automatically, by GitHub Actions, hourly and on every push to
`main`. Every real change happens in Google Calendar (for events), the
rest of `/config` (other data), or `/src/templates` (layout), followed by
a rebuild — and pushing to `main` is what actually makes it live, since
GitHub Actions does the rebuild-and-deploy for you.

**If you're an AI agent (Claude or otherwise) making a content change**:
check `.claude/skills/` first — there's a dedicated skill for each kind of
addition (board member, sponsor, flyer/document). Events are the one
exception: they're calendar-driven now, not a config edit — see
`.claude/skills/add-event/` and Task 4 below. Skills are scoped to
**config-only edits** and are the preferred path. Only touch `src/` if the
user explicitly asks for a structural/design change.

Requires only Python 3 — no npm, no installs, nothing to configure.

---

## Task 1 — Change site info (name, address, contact, links)

**Emails on the website**: only PTA addresses (`…thespta@gmail.com`) and
addresses the PTA has approved one by one appear on the site. The
approved list is `approved_emails` in `config/site.json`. Any other
address — even one typed into a calendar event's description — is
automatically **hidden** (left off the page, nothing in its place) when
the site builds, and the build log names it. Whoever next works on the
site asks the PTA about it; to approve it, add it to `approved_emails`.

**File:** `config/site.json`

| Field | Controls |
|---|---|
| `org_name`, `school_name`, `school_short_name` | Name shown throughout the site |
| `mascot_name` | "Home of the ___" text on the banner |
| `address_line1` / `address_line2` | Footer address |
| `email` | Footer contact link |
| `meeting_schedule`, `membership_cost` | Text on About / Get Involved |
| `donate_href` | Where the "Donate" buttons point (Support THES card). Currently the Givebacks shop pre-filtered to donation items: `https://1thes.givebacks.com/shop?search=Donation` |
| `membership_portal_href` | Where "Join PTA" / "Become a Member" buttons point. Currently the Givebacks shop pre-filtered to membership items: `https://1thes.givebacks.com/shop?search=Membership` — the shop lists each membership tier (student, individual, faculty/staff, business, etc.) as a separately named product, and this one search catches all of them. If a tier ever needs its own dedicated link instead, add a new `*_membership_href` field per tier and wire it in wherever that tier should link. |
| `shop_href` | The Givebacks shop's own landing page (`https://1thes.givebacks.com/shop`) — linked from the `/shop` page's "Visit the PTA Shop" button |
| `spirit_wear_shop_href` | The seasonal spirit wear store (a separate site, e.g. `thunderhillfall2026.itemorder.com`) linked from the `/shop` page's "Shop Spirit Wear" button. **This URL is seasonal — it changes name each time a new spirit wear sale opens** (fall/winter/spring), so check it's still live occasionally and update it when a new sale replaces the old one. |
| `google_analytics_id` | Your Google Analytics 4 "Measurement ID" (looks like `G-XXXXXXXXXX`, from [analytics.google.com](https://analytics.google.com) → Admin → Data Streams → your web stream). When set, the exact `gtag.js` snippet Google gives you is placed immediately after `<head>` opens on **every** page — one config value, no per-page work. Set it to `""` (not `null`) to remove tracking from the site entirely. |
| `social.facebook_href`, `social.instagram_href` | Footer social links |
| `newsletter_href` | Footer "Subscribe" link, and the "Subscribe for Future Issues" button on the THES Happenings page — the real Smore newsletter URL |
| `newsletter_embed_src` | The Smore URL actually embedded as an iframe on the THES Happenings page (same newsletter, with `?embedded` appended) — update both together if the Smore newsletter's URL ever changes |
| `custom_domain` | The site's real domain (`www.thespta.org`) — `src/build.py` generates the `CNAME` file GitHub Pages needs from this value on every build. Only touch this if the domain itself changes; see `docs/github-pages-setup.md` for the DNS side. |
| `page_urls.*` | The filename-minus-`.html` slug for each page (e.g. `"index"` for Home, `"get-involved"`) — every internal link resolves as a plain relative filename (`index.html`, `get-involved.html`), which works identically whether the page is reached via the custom domain or the raw `*.github.io` URL. Home is named `index.html` on purpose, so it loads automatically at the domain root — the `page_urls` *key* is still `home` (used throughout templates as `{{page_urls.home}}`), only the underlying filename/value is `index`. |
| `nav` | The header menu's contents, in display order — see Task 5 |
| `copyright_year` | Footer copyright line |

Rebuild + push: `python3 src/build.py` then `git push` (or just push — see Task 7).

---

## Task 2 — Change colors or fonts

**File:** `config/theme.json`

Every color on the site is one named role in `theme.json`'s `colors`
block — change a hex value once here, it updates everywhere that role is
used, on every page, the next time you rebuild. There's no other place
colors live: templates only ever reference a role by name (e.g.
`var(--teal)`), never a hardcoded hex, so this file is genuinely the one
place to edit.

| Role | Default | Where it shows up |
|---|---|---|
| `navy` | `#073B68` | Headings, footer, featured event card, event-date badges, step numbers |
| `yellow` | `#FFD719` | Small cheerful accents only — icon circles, and highlights on the navy featured-event card. Deliberately *not* used for big surfaces or primary buttons. |
| `yellow_text` | `#8A6C00` | Text color paired with a yellow icon-circle background (needs to stay dark for contrast) |
| `teal` | `#159C9C` | Links, eyebrow labels, hover states, and every primary "join in" CTA button (Explore Our Committees, Join the PTA, Volunteer with \_\_\_, etc.) |
| `teal_tint` | `#E1F3F3` | "Members Welcome" committee status badge |
| `coral` | `#F2645A` | One of the "who benefits" icon colors; "Chair Needed" committee status badge |
| `coral_tint` | `#FDE7E5` | "Chair Needed" committee status badge background |
| `bg_tint` | `#EAF6F1` | The alternating section background (a warm light teal) used sitewide for visual rhythm between white and tinted sections — never applied to hero/banner photos |
| `text` / `text_muted` | `#172B3D` / `#566878` | Body text / secondary text |
| `border` | `#DCE5EA` | Card borders (light blue-gray) |

To recolor the site's teal accent everywhere at once, change `teal` (the
saturated version, used for links/buttons/text) and `bg_tint` (its very
light background counterpart) — those two together are what create the
white/teal alternating look. Secondary/utility buttons (calendar
subscribe, newsletter subscribe, membership portal) intentionally stay
navy rather than teal, for visual hierarchy against the primary teal
CTAs — see `src/templates/tokens.html.tmpl`'s `.thes__btn--navy` /
`.thes__btn--teal` if you ever want to change which buttons use which.

Fonts are set under `fonts.display` (headings — Montserrat) and
`fonts.body` (paragraphs — Lato). To change either, you need a font name
Google Fonts actually has, and you must update `google_fonts_url` to match
(go to [fonts.google.com](https://fonts.google.com), pick the font, copy
the `<link>` URL it gives you).

---

## Task 3 — Add, remove, or edit a board member

**File:** `config/board.json` · **Skill:** `.claude/skills/add-board-member/`

Each entry is `{ "role": "...", "name": "...", "email": "...", "photo_filename": "..." }`.
`role` and `name` are required; `email` and `photo_filename` are both
optional — a seat with no photo gets a neutral placeholder icon instead
of a broken image, and a vacant seat (`"name": "Vacant"`) should have
neither. Photo files go in `assets/images/` (flat, no subfolder), same as
the hero/page-header images. Add a new `{ }` entry (comma-separated) for
a new board member, delete one to remove someone (or set its name to
`"Vacant"` if the seat still exists but is unfilled), or edit the text
directly. This list appears once, on the About page.

---

## Task 4 — Add, remove, or edit an event

**There is exactly one place to do this: Google Calendar.** Both the
"Upcoming Events" preview on the Home page and the quick-scan list on the
Events page are synced automatically from the PTA's Google Calendar —
nothing to edit in this repo for a routine event change.

1. Go to [calendar.google.com](https://calendar.google.com), find the
   PTA's shared calendar in the left sidebar (matches the `calendar_id` in
   `config/site.json` under `calendar`).
2. Add/edit/delete events as normal — a one-time event, or a recurring one
   (e.g. "First Tuesday of every month" for board meetings) both work.
3. **To attach a flyer to an event** (so it shows as a "Flyer" link next
   to that event on the website): open the event → **Add attachment** →
   pick or upload the file in Google Drive. The Drive file itself still
   needs to be shared **"Anyone with the link"** — attaching it to the
   event doesn't change its Drive sharing, and a visitor clicking a
   flyer link they can't open is the most likely thing to go wrong here.
4. The live calendar embed on the Events page updates within minutes,
   automatically, no rebuild needed.
5. The Home/Events highlight lists (and any flyer link) catch up on the
   next sync — automatically, within the hour
   (`.github/workflows/sync-events.yml`), and again on every push to
   `main`. To pull the change in immediately instead of waiting:
   **Actions** tab → "Sync events from Google Calendar" → **Run
   workflow**.

**`config/events.json` is now generated, like `pages/*.html`  — don't
hand-edit it,** it'll be overwritten by the next sync. `scripts/sync_calendar_events.py`
reads the calendar's public `.ics` feed and picks up to 6 of the soonest
upcoming events (further out ones just don't make the short-list — the
full calendar embed always has everything regardless), auto-marking the
very next one as "featured" for the big navy card on the Home page. A
`description` for the featured card comes from that event's own
Description field in Google Calendar if you set one, otherwise a generic
line is used. Every other event on the quick-scan list shows its own
Description too, if it has one — otherwise that row just stays compact
(date/time/title only), no filler text. A file attached to an event in
Google Calendar (step 3 above) comes through the same way, as a "Flyer"
(or "Flyers", if more than one) link on that event wherever it appears on
the site — shown as a small clickable thumbnail preview, not just plain
text, if the attachment is a Drive link (true of anything attached via
the Calendar UI's own "Add attachment" picker). Drive can generate a
preview thumbnail for a PDF as well as an actual image file, so either
kind of flyer shows a picture, not just a link.

**To add a "Sign Up" button to an event** (a SignUpGenius link, a Google
Form, anything): open the event in Google Calendar and mention "sign up"
somewhere near the link in its Description — natural phrasing is fine,
it doesn't need to be an exact format. All of these work:

```
Sign Up: https://your-signup-link-here
Please sign up here: https://your-signup-link-here
Fun for the whole family! And sign up here! https://your-signup-link-here
```

(Confirmed against a real event — the actual PTA Calendar text was the
free-form third style above, not a dedicated line, and it parsed
correctly.) Only the URL itself is removed from the description shown on
the site — the surrounding sentence stays, and a "Sign Up →" button
appears too: a full button on the Events page and on the Home page's big
featured card, or a smaller "Sign Up →" text link on the Home page's
compact "more events" row if the event isn't the featured one. There's
no dedicated Calendar API field for this the way there is for
attachments, so this loose, tolerant text convention is
what `scripts/sync_calendar_events.py`'s `extract_signup_href` looks for.

**A Google Meet link works the same way, automatically — no keyword
needed.** If an event's Description contains a `https://meet.google.com/...`
link anywhere (Google Calendar puts one there by default for a
Meet-enabled event), it becomes a "Join Google Meet →" button — yellow,
not teal, so it reads as a distinct action from Sign Up if an event
happens to have both. Same deal: only the URL is removed from the
description text, and a dangling separator right before it (Google
Calendar's own default phrasing is "Join Virtually: Google Meet —
<link>") is cleaned up too. See `extract_meet_href` in
`scripts/sync_calendar_events.py`.

**Heads up:** a recurring event (e.g. a monthly meeting) produces one
highlight-list entry per occurrence, so it can crowd out one-off events
further out if there are more than 6 items competing for the list. If
that becomes a real problem, the fix is changing `MAX_EVENTS` in
`scripts/sync_calendar_events.py` (a `src/`-adjacent change — get sign-off
first, per `.claude/CLAUDE.md`) or splitting recurring meetings onto a
separate calendar not included in the sync.

If the calendar has zero upcoming events, both highlight sections
disappear from the site entirely (same empty-list-means-no-section
pattern as sponsors/flyers) — the site never shows an empty "Upcoming
Events" box.

**If the PTA ever switches to a different Google Calendar** (new
account, etc.): update `calendar.calendar_id` (and `calendar.timezone` if
needed) in `config/site.json` and push. The embed, the sync script, the
"Add to Google Calendar" button, the Apple/Outlook subscribe link, and the
`.ics` download link are all built from that one ID — you never edit those
URLs by hand.

### Featured event pages (so people can find an event on Google)

Calendar events only appear in the Events page's rolling list. For an
event you want people to find by searching — like the Holiday Market —
add an entry to `config/event-pages.json` (see
`.claude/skills/add-event-page/SKILL.md` for the fields). That creates:

- its own page at `www.thespta.org/events/<slug>.html` with the flyer,
  details, and the hidden event data Google uses to show it as an event
  in search results,
- a link to it under the **Events** menu (using its short `nav_label`),
- a "Featured Events" card at the top of the Events page.

Only events listed there get a page — nothing is added automatically
from the calendar. Each page is edited independently through its own
entry.

**Expiration**: every featured page has an `expires` date (the last day
it's shown — defaults to the day the event ends). Within the hour after
that, the automatic pipeline moves the entry to
`archive/event-pages.json` and its flyer to `archive/flyers/`, and the
page, menu link, and card all come down. Archived entries stay in the
repo for reference; to reuse one next year, copy it back with new dates.

After it's live, open [Google Search Console](https://search.google.com/search-console),
paste the page's URL into **URL Inspection**, and click **Request
indexing** — then share the link everywhere you promote the event.

---

## Task 4b — Add, remove, or edit a sponsor

**File:** `config/sponsors.json` · **Skill:** `.claude/skills/add-sponsor/`

Each entry is `{ "name": "...", "href": "..." }`. This list is empty by
default (`[]`) — **when it's empty, the whole "Our Sponsors" section on
the Home page doesn't appear at all**, not even as an empty heading. Add
your first entry and the section appears automatically; delete the last
one and it disappears again.

---

## Task 4b-2 — Change sponsorship levels or benefits

**File:** `config/sponsorship.json`

This drives the "Sponsorship Levels" content on the standalone Sponsors
page (`pages/sponsors.html`, linked from a "Become a Sponsor" band on the
Ways to Give page) — the tier names/prices/benefits, the "why sponsor"
list, the "all sponsors receive" perks, and the contact line. It's a
single object, not a list — edit fields/tiers in place. This is
*separate* from `config/sponsors.json` (Task 4b below), which is the
list of businesses that have actually joined and shows just below this
content on the same page, reusing the Home page's "Our Sponsors"
section.

---

## Task 4c — Add, remove, or edit a flyer / document

**File:** `config/flyers.json` · **Skill:** `.claude/skills/add-flyer/`

Each entry is `{ "title": "...", "description": "...", "href": "..." }` —
`href` can be a Google Drive share link (upload the PDF/doc to Drive,
share it "Anyone with the link", copy the link) since this is a normal
read-only share, not an automated upload. Same empty-list-means-no-section
behavior as sponsors — this powers the "Documents & Flyers" section on the
About page, for standing documents (bylaws, handbooks) not tied to a
specific date.

**A flyer for a specific event doesn't go here** — attach it to that
event in Google Calendar instead (Task 4, step 3) so it shows up linked
from that event directly, wherever the event appears.

---

## Task 4d — Add, remove, or edit an announcement

**File:** `config/announcements.json` · **Skill:** `.claude/skills/add-announcement/`

Each entry is `{ "text": "...", "href": "..." }` (external link) or
`{ "text": "...", "page_url": "..." }` (internal page — a key from
`page_urls` below). Same empty-list-means-nothing-shown behavior as
sponsors/flyers — this powers the horizontal announcements banner shown
just under the header on *every* page of the site, not just one.

With more than one entry, the banner auto-rotates between them with a
smooth fade — each message is fully readable for 4 seconds. A visitor can dismiss it (×) — that's
remembered per-browser, but only for the exact set of announcements
they dismissed: editing this file in any way (even just fixing a typo)
automatically re-shows the banner to everyone, since dismissal is keyed
to a hash of the content, not "the banner" in general.

Keep each message to **60 characters or fewer** — longer ones wrap to a
third line on phones and make the banner grow. Use short dates ("Nov 21")
and let the linked page carry the details.

Add `"expires": "YYYY-MM-DD"` (the last day it should show) and it takes
itself down: within the hour after that date, the automatic pipeline
moves it to `archive/announcements.json` for reference and redeploys.

---

## Task 5 — Add, remove, or reorder a nav menu item

**File:** `config/site.json` → `nav`

Each entry is `{ "label": "...", "page_url": "<a page_urls.* key>" }`.
Order in the list is left-to-right display order in the header. To add
an existing page to the menu, add an entry pointing at its `page_urls`
key; to remove one from the menu (without deleting the page itself),
delete its entry.

An entry can also carry a `"children"` list (same shape) to become a
dropdown — desktop shows it on hover, mobile lists it indented inside
the already-open mobile menu:

```json
{ "label": "Resources", "page_url": "resources", "children": [
  { "label": "Bylaws", "page_url": "bylaws" },
  { "label": "Committees", "page_url": "committees" }
] }
```

Omit `"page_url"` on a parent entry to make it a dropdown-only label with
no page of its own. **Adding a genuinely new page** (not just adding an
existing one to the nav) is a bigger step — new template, new
`page_urls` entry — that's a `src/` change; ask before doing it, per
`.claude/CLAUDE.md`.

---

## Task 5b — Add, remove, or edit a committee

**File:** `config/committees.json` · **Skill:** `.claude/skills/add-committee/`

All committees live on **one** page, `/get-involved/committees` — there's
no per-committee page or URL, by design (so adding a committee is a
one-line config change, not a new page). Each entry:

```json
{ "name": "Hospitality", "slug": "hospitality", "status": "chair-needed", "chair": null,
  "description": "...", "activities": ["...", "..."], "audiences": ["staff"],
  "volunteerValue": "Hospitality" }
```

`status` (`"chair-needed"` or `"members-welcome"`) controls which of the
page's two sections the card appears in and which badge it shows —
moving a committee between them is just changing this one field (and
`chair`, to match). See the skill for the full field reference.

### One-time setup: the shared volunteer Google Form

Every committee's "Volunteer with ___" button opens the **same** Google
Form, with the committee name pre-filled via a
[prefilled-link URL](https://support.google.com/docs/answer/9308501) —
`config/site.json`'s `volunteerForm` block controls this for every
committee at once:

```json
"volunteerForm": {
  "baseUrl": "https://docs.google.com/forms/d/e/REPLACE_WITH_REAL_FORM_ID/viewform",
  "committeeFieldId": "entry.REPLACE_WITH_REAL_ENTRY_ID"
}
```

**This ships with placeholder values that don't go anywhere real yet.**
To wire up the actual form:

1. Create the Google Form (one "Committee" short-answer or dropdown
   field, plus whatever else you want to collect).
2. In the form editor, click the **⋮** menu → **Get pre-filled link**.
3. Fill in the Committee field with any sample value, fill in nothing
   else that should stay blank, then click **Get link**.
4. Copy the generated URL — it looks like
   `https://docs.google.com/forms/d/e/1FAI.../viewform?usp=pp_url&entry.123456789=Sample`.
   Split it into the two config values:
   - `baseUrl`: everything up to (not including) the `?` —
     `https://docs.google.com/forms/d/e/1FAI.../viewform`
   - `committeeFieldId`: the `entry.XXXXXXXXX` part right before `=Sample`
     (drop `usp=pp_url` and the `=Sample` value — the site builds that
     part itself per committee).
5. Update both values in `config/site.json`, rebuild, and check a few
   "Volunteer with ___" buttons on the live Committees page actually land
   on the form with the right committee pre-filled.

---

## Task 5c — Add, remove, or edit an afterschool program

**File:** `config/afterschool-programs.json` · **Skill:** `.claude/skills/add-afterschool-program/`

Every program on `/before-after-school-programs` is run by an outside provider
(iCode, KidzArt, a theatre company, etc.) — **not** the PTA or the
school — so the page says so explicitly, and every card is expected to
carry its own registration link/contact info. Each entry's flyer is a
plain image file in `assets/flyers/before-after-school/` in this repo,
shown as a thumbnail exactly the way an event's calendar attachment
already is.

(This used to be a shared Google Drive folder read via the Drive API.
That was migrated into the repo after the account that owned the folder
got flagged by Google, and every file in it — even ones on a plain
public link — started returning "you can't access this item, it
violates our Terms of Service." Nothing about a personal account's
standing can take this down anymore.)

### Adding a flyer

Anyone with repo write access can drop a flyer in without touching git
directly: on GitHub's website, go to
`https://github.com/techmaster-thespta/thespta/upload/main/assets/flyers/before-after-school`,
drag the image in, write a commit message, and commit. The next push
(this one included) runs the sync below automatically.

### This page is normally kept up to date automatically

`scripts/sync_afterschool_flyers.py` runs as a step in
`.github/workflows/deploy.yml` — on *every* push, not on a schedule, since
a file landing in the repo is itself the event; there's no external
state left to poll for. It reconciles `config/afterschool-programs.json`
against whatever's actually in `assets/flyers/before-after-school/`:

- A flyer file removed from that folder → its card disappears.
- A brand-new flyer → a placeholder card appears (name guessed from the
  filename, flagged `"needs_review": true`) until someone fills in the
  real program details.
- A changed flyer (same filename, different content) → flagged
  `"needs_review": true`, old details left in place rather than wiped.

**Reading what a flyer actually says (writing the real name, schedule,
price, description) is not something this automation can do on its
own** — that's the same kind of visual-understanding task the first
version of this page was built with. Whenever an entry is flagged
`needs_review`, open `assets/flyers/before-after-school/<flyer_filename>`
(or ask an agent to), read the flyer, and update the entry by hand —
then clear the flag. See
`.claude/skills/review-afterschool-flyers/SKILL.md` for the full
process; the daily `scripts/flyer-review/` service also runs this
automatically (see `docs/automation-service.md`).

---

## Task 5d — Add, remove, or edit a fundraising campaign

**File:** `config/fundraisers.json` · **Skill:** `.claude/skills/add-fundraiser/`

Every campaign on `/fundraising` ("Ways to Give") is the PTA's own —
unlike afterschool programs, these aren't third-party providers running
something at the school. Each entry belongs to one of five `category`
values (`recurring`, `seasonal`, `annual`, `everyday`, `direct`) that
control both its badge and which section of the page it lands in — see
the skill file for what each means. Flyers live in
`assets/flyers/fundraising/` in this repo (same Drive-to-repo migration
as Task 5c, for the same reason).

**Current Fundraisers (automatic)**: the top of Ways to Give lists every
Google Calendar event with **"Fundraiser" in its title** that's running
now or starts within about 60 days, and drops it the day after it ends —
just add the fundraiser to the calendar. For a richer card (sign-up
links, a seller code), add an entry to `config/fundraisers.json` with
`"calendar_match": "<words from the calendar title>"` (e.g. `"Joe
Corbi"`): it replaces the plain calendar card and only shows while that
calendar event is current, so it can stay in the file for next year.
Restaurant nights keep their own card (no "Fundraiser" in their titles).

### Adding a flyer

Same as Task 5c, just the other folder:
`https://github.com/techmaster-thespta/thespta/upload/main/assets/flyers/fundraising`.

### This page is normally kept up to date automatically

`scripts/sync_fundraiser_flyers.py` runs as a step in
`.github/workflows/deploy.yml` on every push — same mechanism as the
afterschool sync (Task 5c), with one real difference: a fundraiser
campaign isn't flyer-dependent the way an afterschool program is. Box
Tops, RaiseRight, and the rest stay on the page even if their current
flyer image is removed from the folder (the flyer is just detached, not
the campaign deleted) — only an unreviewed placeholder that never got
real content is removed when its flyer disappears. And because a *new*
flyer file is often a reprint of a campaign that's already on the page
rather than a genuinely new one (this actually happened — a flyer named
"buy-a-box.jpg" turned out to be the See's Candies flyer), the sync
script makes a conservative filename-vs-campaign-name guess before
creating a placeholder, so an obvious reprint gets attached to its
existing card automatically instead of creating a duplicate.

**Neither the mechanical sync nor a filename guess can write real
campaign details, or tell a reprint from a genuinely new flyer with full
confidence** — that requires actually looking at the flyer. Whenever an
entry is flagged `needs_review`, open
`assets/flyers/fundraising/<flyer_filename>` (or ask an agent to), look
at it, and either fill in a new campaign's real details or merge a
reprint into the existing campaign it actually belongs to — then clear
the flag. See `.claude/skills/review-fundraiser-flyers/SKILL.md` for the
full process; the daily `scripts/flyer-review/` service also runs this
automatically.

---

## Task 5e — Add, remove, or edit a PTA meeting record

**File:** `config/pta-meetings.json` · **Skill:** `.claude/skills/add-pta-meeting/`

`/pta-meetings` is a permanent archive, different in kind from
`/events`: the calendar shows a meeting is *coming up*, with an
invitation-style description; this page records what actually
*happened*, after the fact, once a recap flyer or real highlights
exist to report. The single most recent meeting is spotlighted at the
top of the page; every other one is grouped into a `<details>`
accordion by school year (July–June).

### This page is normally kept up to date automatically

Same mechanism as Tasks 5c/5d: `scripts/sync_pta_meeting_flyers.py`
runs as a step in `.github/workflows/deploy.yml` on every push and
reconciles `config/pta-meetings.json` against whatever's actually in
`assets/flyers/pta-meetings/` — a flyer removed means the record is
removed, a new flyer means a placeholder appears flagged
`needs_review`. One real difference from the other two: a brand-new
placeholder gets **no guessed date** (the other flyer types guess a
*name*) — a wrong date would silently misfile the meeting into the
wrong school year, so a dateless placeholder stays visibly incomplete
(shown as a small "N new meeting flyers need review" notice) instead of
ever becoming the page's spotlight or joining a year's archive.

**Reading the flyer to fill in the real date, title, and highlights is
not something this automation can do on its own.** PTA meeting recap
flyers typically state the highlights directly (new board members,
committees formed, membership numbers), so this is usually transcribing
what the flyer already says. Whenever an entry is flagged
`needs_review`, open `assets/flyers/pta-meetings/<flyer_filename>` (or
ask an agent to), read it, fill in the real fields, and clear the flag.
See `.claude/skills/review-pta-meeting-flyers/SKILL.md` for the full
process; the daily `scripts/flyer-review/` service also runs this
automatically.

### One-time setup

None — this reuses the same repo-hosted-flyer mechanism as Tasks 5c/5d,
no credentials of any kind needed. Drop a flyer at
`https://github.com/techmaster-thespta/thespta/upload/main/assets/flyers/pta-meetings`
via GitHub's web UI (or push one directly) and the next deploy picks it
up.

---

## Task 5f — Add, remove, or edit a family support resource

**File:** `config/family-support-resources.json` · **Skill:** `.claude/skills/add-family-support-resource/`

`/family-support-resources` is a landing page of cards pointing to
Howard County / community resources the PTA doesn't run itself —
distinct from Events and PTA Meetings, which are both PTA-run. Most
cards just link straight out to an external page; the first one
(**Special Education & Family Support**) links to a page on this site
instead, because it's substantial enough to warrant its own (a live
HCPSS calendar embed plus reference links) — see
`src/templates/pages/family-support-resources/special-education-family-support.html.tmpl`.
That sub-page's calendar embed and reference links are HCPSS's own —
nothing to sync or maintain; the calendar stays current on its own.

A plain resource card (external link, or linking to a page that already
exists) is config-only. Giving a *new* resource its own page is a
`src/` change — see the skill file's "Adding a resource that needs its
own page" section, and get sign-off first per `.claude/CLAUDE.md`'s
"Adding a new modular content type" rule.

---

## Task 6 — Change the banner photo, page header photo, or add a logo

Images live in `assets/images/` in this repo and are served directly by
GitHub Pages alongside the HTML — no external hosting, no sharing settings
to manage.

1. Drop the new image file into `assets/images/`.
2. Update `config/site.json` — `hero_image_filename` (Home banner) or `page_header_image_filename` (About/Get Involved/Events header) to that filename.
3. Push. GitHub Actions rebuilds, copies it into the deployed site's `images/` folder, and it's live.

There's no logo yet (`thes__icon-circle` fallbacks and text stand in for
one). When there's a real Thunderbird logo file, it can be added the same
way.

---

## Task 7 — Publish a change

The site is served directly from what's in this repo, so publishing a
content change is just:

```bash
python3 src/build.py     # optional — CI does this too, but good to check locally
git add -A
git commit -m "describe the change"
git push
```

GitHub Actions takes it from there: rebuilds, validates, commits
regenerated `pages/` back if needed, and redeploys to GitHub Pages —
`https://www.thespta.org` shows the update automatically.

**Want it live immediately** instead of waiting on the push-triggered
pipeline or the hourly calendar sync? Trigger a rebuild directly:
**Actions** tab → "Build, validate, and deploy to GitHub Pages" → **Run
workflow**. If you're asking an AI agent to do this, it's the
`rebuild-now` skill (`.claude/skills/rebuild-now/`).

**Want a shareable summary of what's new** — e.g. to send the board an
update? That's a release, not just a push: ask an AI agent to use the
`release` skill (`.claude/skills/release/`), which bumps `VERSION`,
writes a plain-language entry in `CHANGELOG.md`, and cuts a tagged
GitHub Release at
`https://github.com/techmaster-thespta/thespta/releases`. Only do this
when you actually want a shareable snapshot — not after every small
change.

---

## Verification checklist (before/after pushing)

- [ ] `python3 test/validate_build.py` passes with no failures (or the GitHub Actions run for your commit is green — check the **Actions** tab).
- [ ] Visit the live URL directly (e.g. `https://www.thespta.org/`) to confirm the change is really there.
- [ ] If you changed `theme.json`, spot-checked every page, not just one — colors are shared.

---

## Yearly board handoff

- This GitHub repo (`techmaster-thespta/thespta`) is the source of truth — hand off repo access (or add the incoming board's GitHub account as a collaborator) along with this doc.
- Nobody needs to know Python to use it — just edit the `.json` files listed above and push; GitHub Actions rebuilds and redeploys automatically.
- The Google account used for Google Calendar should be a shared PTA/"webmaster" account, not a personal one, so ownership doesn't leave with a board member.
- Whoever manages `thespta.org`'s DNS (domain registrar access) needs to be someone with institutional continuity too — that's a separate credential from GitHub/Google and only needed if the domain itself ever moves (see `docs/github-pages-setup.md`).

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Banner or header image is broken | Filename in `config/site.json` doesn't match a real file in `assets/images/` | Check spelling/extension match exactly, rebuild |
| Calendar embed shows blank/error | Calendar's own sharing isn't public, or wrong `calendar_id` | In Google Calendar → calendar settings → **Access permissions** → "Make available to public" |
| `www.thespta.org` shows an old version | Should always be live within a minute or two of a successful deploy | Hard-refresh to rule out browser caching; check the **Actions** tab for a recent green run |
| `python3 src/build.py` prints `unresolved placeholder(s)` | A config file is missing a field a template expects | Read the warning — it names the exact `{{key}}` — add that field to the relevant `config/*.json` |
| Layout looks broken/overlapping on phone | Usually a hand-edited style with a fixed pixel width or `position: absolute` added outside the existing patterns | Stick to the existing CSS classes in `src/templates/tokens.html.tmpl` rather than adding new inline styles with fixed widths |
| GitHub Actions run failed | See `docs/github-pages-setup.md` → "If something breaks" | |
| Custom domain broken (SSL warning, wrong content, "domain not verified") | DNS or GitHub Pages custom-domain config issue, not a code problem | See `docs/github-pages-setup.md` → "Point the custom domain at GitHub Pages" |
