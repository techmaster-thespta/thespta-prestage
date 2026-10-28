---
name: add-sponsor
description: Add, edit, or remove a business sponsor listed on the Home page. Config-only — never edit src/.
---

# Add / edit / remove a sponsor

Use this when the user asks to add, change, or remove a business/community
sponsor shown in the "Our Sponsors" section of the Home page.

## File

`config/sponsors.json` — a JSON array, empty (`[]`) by default. Each entry:

```json
{ "name": "Columbia Family Dentistry", "href": "https://example.com" }
```

`name` is required. `href` should be the sponsor's actual website;
leave it out entirely when the sponsor has none or the user asks not to
link it — the card then shows no "Visit" link and the logo isn't
clickable. Never use `"#"`.

Optional fields (all rendered by `render_sponsor_card()` in `src/build.py`,
same card on the Home page and the Sponsors page):

- `logo_filename` — a logo image in `assets/images/` (flat — the deploy
  copies only that folder's top level), named `sponsor-<name>.png`.
  Prefer a transparent PNG; trim empty margins and keep it ~400px.
- `tier` — the level they bought, matching `config/sponsorship.json`'s
  tiers without the word "Sponsor" (`"Presenting"`, `"Gold"`,
  `"Silver"`, `"Community"`); shows as a "<tier> Sponsor" badge.
- `blurb` — one short line about the business (optional).
- The `name` always shows as text under the logo, and in the "Visit
  <name>" link, the Sponsors page's search description, and its
  structured data — so search engines and AI assistants can read who
  the sponsors are (they can't read words inside a logo image). Use the
  business's real, full name.

Cards are ordered and sized by `tier` automatically (Presenting biggest,
then Gold, Silver, Community; file order kept within a level), each with
its level color — no need to reorder `config/sponsors.json` by hand.

Never put the sponsor's contact name, email, or phone from their order
on the site — those are private. A thank-you banner announcement
(`add-announcement` skill) can use the logo as its `icon_filename`.

**Important behavior to know**: when this file is `[]`, the entire "Our
Sponsors" section is omitted from `pages/index.html` — not shown as an empty
heading. Adding the first entry makes the section appear automatically;
removing the last entry makes it disappear automatically. This is by
design — don't "fix" it by editing templates.

## Steps

1. Read `config/sponsors.json`.
2. **Adding**: append a new `{ }` entry. Ask for the sponsor's name and website URL if not given.
3. **Editing**: change the relevant field(s) in place.
4. **Removing**: delete the entry.
5. Run `python3 src/build.py`.
6. Run `python3 test/validate_build.py` — confirm it passes.
7. Report that `pages/index.html` changed (mention explicitly if the section just appeared or disappeared for the first time) and remind the user to push (`docs/SOP.md` Task 7) — GitHub Actions rebuilds and redeploys automatically.

## Do not

- Do not edit `src/templates/card-sponsor.html.tmpl`, `sponsors-section.html.tmpl`, or `src/build.py`. If the request needs different placement or layout, stop and tell the user that's a template change, not a config change, and ask before proceeding.
