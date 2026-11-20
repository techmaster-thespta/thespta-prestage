---
name: add-event-page
description: Feature one specific event with its own searchable page (e.g. the Holiday Market) — Google event structured data, an Events-menu link, auto-archived when it expires — or edit/remove one. Opt-in only; config-only — never edit src/.
---

# Add / edit / remove an event page

Use this when the user wants a particular event to be findable on Google
(e.g. "I want the Holiday Market to show up when people search for it").
This is **opt-in**: routine calendar events stay calendar-only (see the
`add-event` skill). Only events the user explicitly names get a page.

Each entry in `config/event-pages.json` becomes
`pages/events/<slug>.html` with:

- a full page (date/time, location, contact, flyer, detail sections,
  "Add to Google Calendar" button),
- schema.org `Event` JSON-LD in `<head>` (what Google reads to show it
  as an event in search results),
- a `<meta name="description">` from `summary`, a canonical URL, and a
  `sitemap.xml` entry,
- a link under the **Events** nav menu (label: `nav_label`), added
  automatically — never edit `config/site.json`'s nav for this,
- a card in the "Featured Events" section at the top of the Events page.

All of that stays up through the `expires` date (inclusive, Eastern
time) and then comes down on its own: the pipelines run
`scripts/archive_expired.py`, which moves the entry to
`archive/event-pages.json` and its flyer to `archive/flyers/`, and the
build clears the old page out of `pages/events/`.

## File

`config/event-pages.json` — a JSON array, `[]` means no event pages and
no "Featured Events" section. Each entry:

```json
{
  "slug": "holiday-market",
  "title": "THES PTA Holiday Market 2026",
  "nav_label": "Holiday Market",
  "eyebrow": "Save the Date",
  "tagline": "One sentence shown under the title and on the Events page card.",
  "summary": "1–2 sentences naming the event, full date, time, and place — becomes the Google search snippet and the JSON-LD description.",
  "start": "2026-11-21T11:00",
  "end": "2026-11-21T15:00",
  "expires": "2026-11-21",
  "location_name": "Thunder Hill Elementary School",
  "flyer_filename": "events/holiday-market-2026.png",
  "flyer_alt": "Text version of what the flyer says.",
  "about": ["Paragraph.", "Paragraph."],
  "sections": [
    { "heading": "What You'll Find", "items": ["Bullet", "Bullet"], "note": "Optional line under the list.",
      "button_label": "Optional button text", "button_href": "https://..." }
  ],
  "register_href": "",
  "contact_name": "Natalie Miskimins",
  "contact_email": "president.thespta@gmail.com"
}
```

Required: `slug`, `title`, `summary`, `start`. Everything else is
optional. `nav_label` is the short name for the Events menu (defaults to
`title` — keep it short). `expires` is the last day the page is live;
it defaults to the day the event ends, so only set it to keep a page up
longer (e.g. a recap) — always write it explicitly when adding an entry,
computed from the real event date, never guessed. `start`/`end` are local time in `config/site.json`'s
`calendar.timezone` (no offset — the build adds the right EST/EDT one); for an all-day event use a bare date (`"start": "2026-11-11"`).
Location defaults to the school's address from `config/site.json`;
override with `address_line1`/`address_line2` for an off-site event.
`register_href`, when set, adds a "Register as a Vendor" button.
**Vendor map** (e.g. the Holiday Market): set `"vendor_map":
"vendor-maps/<file>.json"` on the entry to get a phone-friendly,
tappable, searchable booth map on its own subpage,
`events/<slug>/vendor-map.html` (shareable by link / QR code), with an
"Open the Vendor Map" button on the event page (`render_vendor_map`,
`render_vendor_map_page` in `src/build.py`). The data file under `config/vendor-maps/` holds every
booth's `number`, `name`, `tags` (food / children / outlet) and its
`col`/`row` on the gym grid, plus `areas` (hallway, cafeteria, ...).
**When vendors move, edit only that file:** change the `name`/`tags` on
the booth number (a swap is two edits), then set `updated` to today.
`col`/`row` only change if the room layout itself changes. Keep the
printable layout image as an `extra_flyers` entry, labeled as possibly
out of date.

**Public vendor list**: `"vendor_list": "vendor-maps/<file>.json"` (the
same file) adds a paged, searchable "Vendors & Tables" list to the event
page itself: vendor names A–Z with no booth numbers, then hallway/PTA/
sponsor tables (items with a tag, or areas with `"public_list":
"tables"`), then other activities. Each vendor (a booth, or an entry in
`unassigned` for confirmed vendors without a booth yet) can carry
`category` (one of the file's `categories`, which become filter chips),
`about` (1–2 sentences) and `links` (website/instagram/facebook/tiktok),
taken from the vendor's own spotlight response; never publish their
contact name or email. `vendor_list` and `vendor_map` are
independent, so the list can be public while the map stays unpublished.
For the 2026 Holiday Market the map is staging-only until the user says
"push the map to prod now".

For an online-only event (e.g. Giving Tuesday), set `online_href` to the
event's URL: the Where line shows `location_name` plus that link instead
of the school's address, and the search data marks it as an online event.

## Steps

1. Get the details from the user or their flyer. **Never guess** a date,
   time, price, or link — ask. Check `config/events.json` / the calendar
   for the same event and make sure the date matches.
2. Save the flyer image into `assets/flyers/events/` (this repo, not a
   Drive link — see the "images" constraint in `.claude/CLAUDE.md`) and
   set `flyer_filename` to `events/<file>`. For a second flyer (e.g. a
   food-vendor update), add `"extra_flyers": [{"filename":
   "events/<file>", "alt": "..."}]` — they render side by side with the
   main one (stacked on phones) and are archived along with it.
3. Add/edit/remove the entry in `config/event-pages.json`. Put the
   event's name, full date, and location — "in Columbia, Maryland
   (Howard County)" — in `summary`: that's the snippet people see in
   search results, and the build prints a `!` warning if it doesn't
   mention Columbia. The page's `<title>` gets "· Columbia, MD" and the
   Where line / event data get "Howard County" automatically — don't
   stuff them into `title` itself.
4. Run `python3 src/build.py` and `python3 test/validate_build.py`.
5. Push (`docs/SOP.md` Task 7). Then remind the user to use Google
   Search Console → URL Inspection → "Request indexing" on the new page
   URL, and to share that link (social, newsletter, community calendars)
   — Google ranks pages other sites link to.

**Removing early** (event cancelled): set `expires` to yesterday and
let the pipeline archive it, rather than deleting the entry — that keeps
the record in `archive/`. Changing a `slug` changes the URL — avoid that
once a page has been shared.

**Reviving an archived event** (an annual one): copy its entry from
`archive/event-pages.json` back into `config/event-pages.json`, drop
`archived_on`, update the dates/`expires`/details, and move its flyer
back from `archive/flyers/` (or add the new year's flyer).

## Do not

- Do not create a page for an event the user didn't ask for.
- Do not edit `src/templates/event-page.html.tmpl` or `src/build.py` for
  a content change — layout changes are a structural change; ask first.
