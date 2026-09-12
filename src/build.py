#!/usr/bin/env python3
"""
Thunder Hill Elementary PTA — static site builder.

Reads /config/*.json + src/templates/*.html.tmpl and writes one complete
HTML file per page into /pages, self-hosted directly on GitHub Pages at
the custom domain in config/site.json's `custom_domain` — no third-party
site builder in the chain. Run this after changing anything in /config
or /src/templates:

    python3 src/build.py        (or: scripts/build.sh)

No dependencies beyond the Python 3 standard library.

WHY THIS EXISTS: this script is what makes "change the color/text once,
it updates everywhere" possible — it lives entirely in this repo, and its
only job is to stamp out the final static files that get deployed.

Pages: home, about, get-involved, events, newsletter — see docs/SOP.md
for the full day-to-day editing guide, and docs/skills for how content
additions (events, board members, sponsors, flyers) are meant to be made
— config only, never this file — by an agent working from .claude/skills/.
"""
import datetime as dt
import json
import re
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
TEMPLATES = Path(__file__).resolve().parent / "templates"
PAGES_OUT = ROOT / "pages"

PLACEHOLDER = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def flatten(d, prefix=""):
    """Turn nested dicts into dotted keys: {"a": {"b": 1}} -> {"a.b": 1}."""
    out = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten(v, key))
        else:
            out[key] = str(v)
    return out


def render(text, context):
    """Replace {{key}} / {{a.b}} placeholders found in `context`; leave any
    placeholder not in `context` untouched (so markers like {{FOOTER}} can
    be substituted in a later pass without this function tripping on them)."""
    def sub(match):
        key = match.group(1)
        return context[key] if key in context else match.group(0)
    return PLACEHOLDER.sub(sub, text)


def indent(text, spaces=6):
    pad = " " * spaces
    return "\n".join(pad + line if line.strip() else line for line in text.splitlines())


def load_json(name, default=None):
    path = CONFIG / name
    if not path.exists():
        if default is not None:
            return default
        raise SystemExit(f"Missing required config file: config/{name}")
    return json.loads(path.read_text())


def build_context(depth=0):
    """`depth` is how many directory levels below the site root the page
    being built lives (0 for a top-level page like about.html, 1 for a
    page one directory down like get-involved/committees.html, etc.) —
    every relative path below is prefixed with the right number of "../"
    so a page can correctly link to any other page or asset regardless of
    how deep either one is nested. Deliberately relative rather than
    root-absolute (e.g. "/about.html"): this repo also gets pushed as-is
    to a staging repo served from a URL *subpath*
    (.../thespta-prestage/...), not the domain root, where root-absolute
    links would silently point at the wrong site."""
    site = load_json("site.json")
    theme = load_json("theme.json")

    context = flatten(site)
    context["font_display"] = theme["fonts"]["display"]
    context["font_body"] = theme["fonts"]["body"]
    context["google_fonts_url"] = theme["fonts"]["google_fonts_url"]
    context.update(flatten(theme["colors"], "colors"))

    prefix = "../" * depth

    # Served by GitHub Pages alongside the HTML — see .github/workflows/deploy.yml,
    # which copies assets/images/* into site/images/ next to pages/*.html.
    context["HERO_IMAGE_URL"] = f'{prefix}images/{site["hero_image_filename"]}'
    context["PAGE_HEADER_IMAGE_URL"] = f'{prefix}images/{site["page_header_image_filename"]}'

    # Same idea, for content-type flyers (afterschool programs,
    # fundraisers) — see .github/workflows/deploy.yml, which copies
    # assets/flyers/** into site/flyers/** next to pages/*.html. These
    # used to be Google Drive hotlinks; moved into the repo after the
    # Drive account got flagged and every file in it — even ones on a
    # plain public link — started 403ing.
    context["FLYER_BASE_URL"] = f"{prefix}flyers"

    # Internal links are plain relative filenames — `about`, `events`, etc.
    # become `about.html`, `events.html` (or `../about.html` etc. from one
    # directory down) — resolved relative to whatever domain serves
    # /pages directly (GitHub Pages' own URL, or the custom domain in
    # `custom_domain` via the generated CNAME file below).
    for key in list(context.keys()):
        if key.startswith("page_urls."):
            context[key] = f"{prefix}{context[key]}.html"

    cal_id = site["calendar"]["calendar_id"]
    cal_id_q = urllib.parse.quote(cal_id, safe="")
    tz_q = urllib.parse.quote(site["calendar"]["timezone"], safe="")
    # `color`: Google's embed defaults an unstyled calendar's events to a
    # pale/white block that barely shows up against the embed's white
    # background — passing our own navy brand color (confirmed Google
    # accepts arbitrary hex here, not just its built-in palette) makes a
    # day with something on it obvious at a glance. `mode=MONTH` makes
    # that explicit rather than relying on the embed's own default.
    color_q = urllib.parse.quote("#" + theme["colors"]["navy"].lstrip("#"), safe="")
    context["CAL_EMBED_SRC"] = (
        f"https://calendar.google.com/calendar/embed?src={cal_id_q}&ctz={tz_q}&color={color_q}&mode=MONTH"
        "&showTitle=0&showPrint=0&showTabs=0&showCalendars=0&showNav=1&showDate=1"
    )
    context["CAL_WEBCAL_URL"] = f"webcal://calendar.google.com/calendar/ical/{cal_id_q}/public/basic.ics"
    context["CAL_GOOGLE_ADD_URL"] = f"https://calendar.google.com/calendar/render?cid={cal_id_q}"
    context["CAL_ICS_URL"] = f"https://calendar.google.com/calendar/ical/{cal_id_q}/public/basic.ics"

    return context


def build_tokens(context):
    return render((TEMPLATES / "tokens.html.tmpl").read_text(), context)


def render_nav_items(items, context):
    """Render config/site.json's `nav` list into <li> menu items.

    Each item is {"label": ..., "page_url": <a page_urls.* key>} and may
    optionally have "children": [...same shape...] for a one-level
    dropdown submenu — this is the hook for a future page to gain
    subpages without touching this function again, just config. A parent
    with children and no page_url of its own (omit "page_url") renders as
    a non-link dropdown trigger rather than a page link.

    A parent item's caret is a real <button> wired to its submenu via
    aria-controls/id (not proximity in the DOM) and toggled by the
    script build_header() appends after the header markup. The JS sets
    the submenu's inline style.display directly rather than toggling a
    CSS class, so opening/closing it can't be silently defeated by a
    media query or selector mistake elsewhere in the stylesheet — an
    inline style always wins the cascade."""
    html = []
    for i, item in enumerate(items):
        label = item["label"]
        href = context[f"page_urls.{item['page_url']}"] if item.get("page_url") else None
        children = item.get("children")
        if children:
            submenu_id = f"thes-submenu-{i}"
            child_html = "".join(
                f'<li><a href="{context[f"page_urls.{c["page_url"]}"]}">{c["label"]}</a></li>'
                for c in children
            )
            trigger = f'<a href="{href}">{label}</a>' if href else f'<span class="thes__nav-trigger">{label}</span>'
            html.append(
                f'<li class="thes__nav-item thes__nav-item--parent">'
                f'<span class="thes__nav-item-row">{trigger}'
                f'<button type="button" class="thes__nav-caret" aria-label="Show {label} submenu" '
                f'aria-expanded="false" aria-controls="{submenu_id}"></button>'
                f'</span>'
                f'<ul class="thes__nav-submenu" id="{submenu_id}">{child_html}</ul></li>'
            )
        else:
            html.append(f'<li class="thes__nav-item"><a href="{href}">{label}</a></li>')
    return "\n".join(html)


def build_header(context):
    nav_items = render_nav_items(load_json("site.json").get("nav", []), context)
    return render((TEMPLATES / "header.html.tmpl").read_text(), {**context, "NAV_ITEMS": nav_items})


def build_footer(context):
    return render((TEMPLATES / "footer.html.tmpl").read_text(), context)


def render_board_photo(member):
    """A board member's headshot, served from assets/images/ like the
    hero/page-header images — or a neutral placeholder for a vacant seat
    (no `photo_filename` in config/board.json), so the grid stays visually
    aligned instead of some cards being taller than others."""
    filename = member.get("photo_filename")
    if filename:
        return f'<img class="thes__board-photo" src="images/{filename}" alt="{member["name"]}">'
    return (
        '<div class="thes__board-photo-placeholder" aria-hidden="true">'
        '<svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">'
        '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.5 4-7 8-7s8 2.5 8 7"/></svg>'
        "</div>"
    )


def render_board_email(member):
    """Omit the email line entirely rather than link to a blank/guessed
    address — not every real board member has a published email, and a
    vacant seat never does."""
    email = member.get("email")
    if not email:
        return ""
    return f'<a class="thes__board-email" href="mailto:{email}">{email}</a>'


def build_board_cards():
    board = load_json("board.json", default=[])
    card_tmpl = (TEMPLATES / "card-board-member.html.tmpl").read_text()
    cards = []
    for member in board:
        ctx = {**member, "PHOTO": render_board_photo(member), "EMAIL_LINK": render_board_email(member)}
        cards.append(indent(render(card_tmpl, ctx)))
    return "\n".join(cards)


DRIVE_FILE_ID = re.compile(r"/file/d/([\w-]+)|[?&]id=([\w-]+)")


def drive_thumbnail_url(href):
    """Drive's public thumbnail endpoint renders a preview image for a
    shared file regardless of type — a real image, or the first page of a
    PDF — confirmed working against a real file before relying on it.
    Returns None if `href` isn't a recognizable Drive share link, so
    non-Drive attachments just fall back to a plain text link."""
    m = DRIVE_FILE_ID.search(href)
    if not m:
        return None
    file_id = m.group(1) or m.group(2)
    return f"https://drive.google.com/thumbnail?id={file_id}&sz=w400"


ATTACHMENT_LINK_TEXT = "Click for more information"


def render_event_attachments(attachments):
    """A file attached to a calendar event (e.g. a flyer PDF or image —
    see scripts/sync_calendar_events.py) becomes a small clickable
    thumbnail preview, or a plain text link when there's no thumbnail to
    show. Returns "" if the event has none.

    The thumbnail is sized big enough that the picture itself is
    recognizable (not just a tiny icon) — that's what signals "there's
    more here," so no "Flyer:" label is needed alongside it, just the
    click-through text. The link text is always ATTACHMENT_LINK_TEXT, not
    the attachment's own filename — Calendar attachments commonly get an
    auto-generated filename (a photo upload UUID, a scan's default name),
    which reads as noise/clutter next to an event, not useful link text."""
    if not attachments:
        return ""
    items = []
    for a in attachments:
        thumb_url = drive_thumbnail_url(a["href"])
        if thumb_url:
            items.append(
                f'<a class="thes__flyer" href="{a["href"]}" target="_blank" rel="noopener">'
                f'<img src="{thumb_url}" alt="" width="160" loading="lazy">'
                f'<span>{ATTACHMENT_LINK_TEXT}</span></a>'
            )
        else:
            items.append(f'<a class="thes__flyer" href="{a["href"]}" target="_blank" rel="noopener"><span>{ATTACHMENT_LINK_TEXT}</span></a>')
    return f'<div class="thes__event-attachments">{"".join(items)}</div>'


def render_event_description(description):
    """An event's own calendar Description, shown as a short blurb under
    its row on the Events page's quick-scan list — "" if it doesn't have
    one (true of most non-featured events), so the row just stays compact
    instead of showing filler text. Separate from the raw `description`
    field the featured-event card template uses directly — that one
    always has a value (falling back to a generic line), this one is
    genuinely optional."""
    if not description:
        return ""
    return f'<p class="thes__event-description">{description}</p>'


def render_event_signup(href):
    """A "Sign Up" button for an event whose calendar Description
    mentioned "sign up" near a URL (see extract_signup_href in
    scripts/sync_calendar_events.py) — "" if it didn't set one, same
    optional-field pattern as attachments/description."""
    if not href:
        return ""
    return f'<a class="thes__btn thes__btn--teal" href="{href}" target="_blank" rel="noopener">Sign Up &rarr;</a>'


def render_event_meet(href):
    """A "Join Google Meet" button for an event whose calendar
    Description had a meet.google.com link (see extract_meet_href in
    scripts/sync_calendar_events.py) — "" if it didn't have one. Yellow
    rather than Sign Up's teal so the two read as distinct actions when
    an event (a hybrid PTA meeting, say) has both."""
    if not href:
        return ""
    return f'<a class="thes__btn thes__btn--yellow" href="{href}" target="_blank" rel="noopener">Join Google Meet &rarr;</a>'


def render_more_event_signup(href):
    """A small "Sign Up" link for an event in the Home page's compact
    "more events" teaser row — that row is deliberately just a title and
    a date (see more-event-row.html.tmpl), so this is a lighter-weight
    treatment than render_event_signup's full button, not a duplicate
    of it. "" when there's no signup_href, same as every other optional
    per-event field."""
    if not href:
        return ""
    return f'<a class="thes__more-events-signup" href="{href}" target="_blank" rel="noopener">Sign Up &rarr;</a>'


def render_more_event_meet(href):
    """Same lighter-weight treatment as render_more_event_signup, for
    the compact "more events" row's Google Meet link instead."""
    if not href:
        return ""
    return f'<a class="thes__more-events-signup" href="{href}" target="_blank" rel="noopener">Join Google Meet &rarr;</a>'


def with_event_extras(event):
    return {
        **event,
        "ATTACHMENTS": render_event_attachments(event.get("attachments", [])),
        "DESCRIPTION_BLOCK": render_event_description(event.get("description")),
        "SIGNUP_BUTTON": render_event_signup(event.get("signup_href")),
        "MEET_BUTTON": render_event_meet(event.get("meet_href")),
    }


def build_welcome_video_section(site):
    """Optional 'welcome video' section on the Home page, right under
    the hero banner — a responsive YouTube embed using the same
    aspect-ratio-box position:absolute technique already vetted for the
    Events page's calendar embed (.thes__cal-frame), just at true 16:9
    instead of that one's taller ratio. youtube-nocookie.com (YouTube's
    own privacy-enhanced embed domain) instead of youtube.com — no
    functional difference, just fewer cookies set for a visitor who
    never presses play. `?rel=0` on the embed URL stops YouTube's
    end-of-video "related videos" panel from pulling in unrelated videos
    from across all of YouTube — confirmed live: without it, a visitor
    who let the PTA's welcome video finish saw an end screen full of
    other channels' thumbnails with unrelated (and not all
    kid-appropriate) titles, which is obviously not something the PTA
    wants surfaced under its own welcome video. "" (no section) when
    config/site.json doesn't set welcome_video_youtube_id, same
    empty-means-no-section pattern as sponsors/flyers/every other
    optional content type on this site."""
    video_id = site.get("welcome_video_youtube_id")
    if not video_id:
        return ""
    return (
        '<section class="thes__section">\n'
        '  <div class="thes__wrap">\n'
        '    <div class="thes__section-head">\n'
        f'      <h2>Welcome to {site["school_short_name"]}!</h2>\n'
        "    </div>\n"
        '    <div class="thes__video-frame">\n'
        f'      <iframe src="https://www.youtube-nocookie.com/embed/{video_id}?rel=0" '
        'title="Welcome video" loading="lazy" allowfullscreen '
        'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; '
        'picture-in-picture; web-share"></iframe>\n'
        "    </div>\n"
        "  </div>\n"
        "</section>"
    )


def build_home_events_section(events, context):
    """Whole 'Upcoming Events' section on the Home page: one big featured
    event (first entry with "featured": true, or the first event) + the
    next two as a short list. Config/events.json is synced automatically
    from Google Calendar (see scripts/sync_calendar_events.py) and can
    genuinely be empty — same empty-list-means-no-section pattern as
    sponsors/flyers, rather than rendering an empty grid."""
    if not events:
        return ""
    featured_tmpl = (TEMPLATES / "featured-event.html.tmpl").read_text()
    more_tmpl = (TEMPLATES / "more-event-row.html.tmpl").read_text()
    section_tmpl = (TEMPLATES / "events-section.html.tmpl").read_text()

    featured = next((e for e in events if e.get("featured")), events[0])
    others = [e for e in events if e is not featured][:2]

    featured_html = indent(render(featured_tmpl, {**context, **with_event_extras(featured)}), 8)
    more_rows = "\n".join(
        indent(render(more_tmpl, {
            **context, **e,
            "SIGNUP_LINK": render_more_event_signup(e.get("signup_href")),
            "MEET_LINK": render_more_event_meet(e.get("meet_href")),
        }), 10)
        for e in others
    )
    return render(section_tmpl, {**context, "FEATURED_EVENT": featured_html, "MORE_EVENTS": more_rows})


EVENTS_PAGE_MAX = 4


def build_events_page_section(events, context):
    """Whole quick-scan highlights section on the Events page. Unlike the
    Home page teaser (which just disappears when there are no events —
    it's a preview, not the main feature), this section always renders:
    with zero synced events it shows a short "nothing posted yet" message
    instead of vanishing, since this list is the site's main date-sorted
    view of what's coming up and a visitor expects to see *something*
    here. The live calendar embed further down the page renders either
    way, regardless of this section.

    Capped at EVENTS_PAGE_MAX (4) events — config/events.json is already
    date-ascending (see scripts/sync_calendar_events.py), so this is
    simply the next 4 chronologically. No "view more" link is needed for
    anything beyond that: the live calendar embed further down this same
    page already shows everything."""
    section_tmpl = (TEMPLATES / "events-list-section.html.tmpl").read_text()
    if not events:
        empty_tmpl = (TEMPLATES / "events-list-empty.html.tmpl").read_text()
        return render(empty_tmpl, context)
    row_tmpl = (TEMPLATES / "event-row.html.tmpl").read_text()
    section_tmpl = (TEMPLATES / "events-list-section.html.tmpl").read_text()
    rows = "\n".join(indent(render(row_tmpl, {**context, **with_event_extras(e)}), 8) for e in events[:EVENTS_PAGE_MAX])
    return render(section_tmpl, {**context, "EVENTS_LIST": rows})


def build_optional_section(config_name, card_template_name, section_template_name, cards_key, context):
    """Generic builder for content types that may have zero entries
    (sponsors, flyers, and any future one like it): renders one card per
    config entry into a section template, or returns "" entirely — so an
    empty config file means the section doesn't appear on the page at all,
    rather than showing an empty heading.
    """
    items = load_json(config_name, default=[])
    if not items:
        return ""
    card_tmpl = (TEMPLATES / card_template_name).read_text()
    cards = "\n".join(indent(render(card_tmpl, item), 8) for item in items)
    section_tmpl = (TEMPLATES / section_template_name).read_text()
    return render(section_tmpl, {**context, cards_key: cards})


def build_family_support_resources_section(resources, context):
    """The Family Support Resources landing page's card grid — same
    empty-means-no-section shape as build_optional_section, but not
    built with it directly: a resource card can link either to a page
    on this site (config gives a `page_url` key, resolved through
    `context` the same depth-aware way nav links are, so it works
    correctly whether this page is at the site root or not — it isn't
    right now, but build_optional_section's cards never resolve
    anything through context at all, so reusing it as-is would silently
    produce a broken relative link) or straight out to an external site
    (config gives `href` instead, opened in a new tab)."""
    if not resources:
        return ""
    card_tmpl = (TEMPLATES / "card-family-support-resource.html.tmpl").read_text()
    cards = []
    for r in resources:
        internal = bool(r.get("page_url"))
        href = context[f"page_urls.{r['page_url']}"] if internal else r.get("href", "")
        link_target = "" if internal else ' target="_blank" rel="noopener"'
        cards.append(indent(render(card_tmpl, {**r, "HREF": href, "LINK_TARGET": link_target}), 8))
    section_tmpl = (TEMPLATES / "family-support-resources-section.html.tmpl").read_text()
    return render(section_tmpl, {**context, "FAMILY_SUPPORT_RESOURCE_CARDS": "\n".join(cards)})


COMMITTEE_STATUS_LABELS = {
    "chair-needed": "Chair Needed",
    "members-welcome": "Members Welcome",
}


def build_volunteer_form_url(volunteer_form, value):
    """A Google Forms "prefilled response" URL — the same form for every
    committee, with the committee field pre-filled to `value`, so no
    per-committee page/link/form is ever needed (config/site.json's
    `volunteerForm` ships with placeholder baseUrl/committeeFieldId until
    a real Google Form exists — see docs/SOP.md for how to get the real
    values from one)."""
    base = volunteer_form["baseUrl"].rstrip("?")
    field = volunteer_form["committeeFieldId"]
    return f"{base}?{field}={urllib.parse.quote(value)}"


def render_committee_card(committee, volunteer_form):
    """One committee's card: status badge, one-line description, chair
    (if any), a volunteer button that deep-links into the single shared
    Google Form with this committee pre-selected, and a native <details>
    disclosure for the rest — no JS, no separate page per committee, no
    modal framework needed for "expand for more" to work on mobile."""
    status = committee["status"]
    chair = committee.get("chair")
    chair_line = f'<p class="thes__committee-chair">Chair: {chair}</p>' if chair else ""
    activities = "".join(f"<li>{a}</li>" for a in committee.get("activities", []))
    status_note = (
        "A chair is still needed for this committee — but you don't need to become chair to help."
        if status == "chair-needed"
        else "This committee already has a chair — members are always welcome."
    )
    form_url = build_volunteer_form_url(volunteer_form, committee["volunteerValue"])
    return (
        '<div class="thes__committee-card">'
        f'<span class="thes__badge thes__badge--{status}">{COMMITTEE_STATUS_LABELS[status]}</span>'
        f'<h3>{committee["name"]}</h3>'
        f'<p>{committee["description"]}</p>'
        f"{chair_line}"
        f'<a class="thes__btn thes__btn--teal" href="{form_url}" target="_blank" rel="noopener" '
        f'aria-label="Volunteer with {committee["name"]}">Volunteer &rarr;</a>'
        '<details class="thes__committee-more"><summary>Learn More</summary>'
        '<div class="thes__committee-more-body">'
        f'<ul class="thes__checklist-plain">{activities}</ul>'
        f"<p>{status_note}</p>"
        "</div></details>"
        "</div>"
    )


def build_committees_section(committees, volunteer_form):
    """Whole committees page body: the two sections the spec calls for
    (chair-needed first, then members-welcome), each a card grid, plus a
    closing "not sure where to help" CTA into the same form with no
    committee — or rather a "help me choose" placeholder value —
    pre-selected. All 10 committees live on this one page; no per-
    committee URLs exist anywhere."""
    chair_needed = [c for c in committees if c["status"] == "chair-needed"]
    members_welcome = [c for c in committees if c["status"] == "members-welcome"]
    chair_needed_html = "\n".join(indent(render_committee_card(c, volunteer_form), 6) for c in chair_needed)
    members_welcome_html = "\n".join(indent(render_committee_card(c, volunteer_form), 6) for c in members_welcome)
    not_sure_url = build_volunteer_form_url(volunteer_form, "Not sure — help me choose.")
    section_tmpl = (TEMPLATES / "committees-section.html.tmpl").read_text()
    return render(section_tmpl, {
        "CHAIR_NEEDED_CARDS": chair_needed_html,
        "MEMBERS_WELCOME_CARDS": members_welcome_html,
        "NOT_SURE_FORM_URL": not_sure_url,
    })


def render_afterschool_program_card(program, context):
    """One afterschool program's card: a short always-visible summary
    (name, provider, one compact meta line, Register button) plus a
    native <details> "Details" disclosure for everything else —
    description, full schedule/sessions, contact, the flyer, fine print.
    Same zero-JS expand/collapse pattern committees already use
    (render_committee_card above); added because showing every field for
    all 10 programs at once on one page read as far too much text.

    Every program is run by an outside provider (iCode, KidzArt, a
    theatre company, etc.), never the school or PTA staff directly —
    but `pta_sponsored` (confirmed per-program with the PTA president,
    since this isn't something a flyer states) distinguishes a program
    the PTA actively reserves space for and sponsors (KidzArt, Chess
    Wizards, the theatre program, iCode, Girls on the Run) from one
    that's simply an outside org (Scouts, Howard County Rec & Parks)
    independently using the building. The flyer image is the source of
    truth for everything else, a plain file in
    assets/flyers/before-after-school/ (previously hotlinked from
    Google Drive; moved into the repo after the Drive account got
    flagged and every file in it started 403ing, even ones on a plain
    public link). `content_hash` on each config entry is bookkeeping
    only (lets a future refresh tell which flyers actually changed vs.
    which are untouched) and is never rendered."""
    summary = [f'<h3>{program["name"]}</h3>']
    if program.get("provider"):
        summary.append(f'<p class="thes__program-provider">{program["provider"]}</p>')
    badges = []
    if program.get("pta_sponsored"):
        badges.append('<span class="thes__badge thes__badge--pta-sponsored">PTA Sponsored</span>')
    if program.get("grades"):
        badges.append(f'<span class="thes__badge thes__badge--age">Grades {program["grades"]}</span>')
    if badges:
        summary.append(f'<div class="thes__program-badges">{"".join(badges)}</div>')

    meta_bits = [b for b in (program.get("day_time"), program.get("price")) if b]
    if meta_bits:
        summary.append(f'<p class="thes__program-meta">{" &middot; ".join(meta_bits)}</p>')

    if program.get("registration_href"):
        summary.append(
            f'<a class="thes__btn thes__btn--teal" href="{program["registration_href"]}" '
            f'target="_blank" rel="noopener">Register &rarr;</a>'
        )
    elif program.get("registration_note"):
        # No link to register with yet (e.g. a "coming soon" program) —
        # the note is the only actionable info this card has, so it
        # belongs in the always-visible summary, not buried behind
        # "Details" where a card with no meta_bits and no button would
        # otherwise show literally nothing below its badges.
        summary.append(f'<p class="thes__program-meta">{program["registration_note"]}</p>')

    details = []
    if program.get("description"):
        details.append(f'<p>{program["description"]}</p>')
    if program.get("date_range"):
        details.append(f'<p>{program["date_range"]}</p>')
    if program.get("show_date"):
        details.append(f'<p>Show: {program["show_date"]}</p>')

    sessions = program.get("sessions") or []
    if sessions:
        rows = "".join(
            f'<li><strong>{s["label"]}:</strong> {s["dates"]} &mdash; {s.get("classes", "")}, {s.get("price", "")}</li>'
            for s in sessions
        )
        details.append(f'<ul class="thes__checklist-plain">{rows}</ul>')

    if program.get("contact"):
        details.append(f'<p>{program["contact"]}</p>')

    flyer_filename = program.get("flyer_filename")
    if flyer_filename:
        flyer_url = f'{context["FLYER_BASE_URL"]}/before-after-school/{flyer_filename}'
        details.append(
            f'<a class="thes__flyer" href="{flyer_url}" target="_blank" rel="noopener">'
            f'<img src="{flyer_url}" alt="" width="160" loading="lazy">'
            f'<span>{ATTACHMENT_LINK_TEXT}</span></a>'
        )

    if program.get("registration_note") and program.get("registration_href"):
        # Already shown in the summary above when there's no
        # registration_href — see there for why.
        details.append(f'<p>{program["registration_note"]}</p>')

    details_html = ""
    if details:
        details_html = (
            '<details class="thes__program-more"><summary>Details</summary>'
            f'<div class="thes__program-more-body">{"".join(details)}</div></details>'
        )

    return f'<div class="thes__program-card">{"".join(summary)}{details_html}</div>'


def build_afterschool_programs_section(programs, context):
    """Whole Before & After School Programs page body (function/config
    names kept the shorter "afterschool" name for simplicity even after
    the page itself was retitled to explicitly cover before-school
    programs too). Same empty-means-no-content pattern as
    sponsors/flyers/events, except this page always exists (it's in the
    nav) so an empty config shows a short "nothing posted yet" message
    rather than the page vanishing."""
    if not programs:
        return (TEMPLATES / "afterschool-programs-empty.html.tmpl").read_text()
    cards = "\n".join(indent(render_afterschool_program_card(p, context), 6) for p in programs)
    section_tmpl = (TEMPLATES / "afterschool-programs-section.html.tmpl").read_text()
    return render(section_tmpl, {"AFTERSCHOOL_PROGRAM_CARDS": cards})


FUNDRAISER_CATEGORY_LABELS = {
    "recurring": "Recurring Fundraiser",
    "seasonal": "Seasonal Sale",
    "annual": "Annual Drive",
    "everyday": "Everyday Giving",
    "direct": "Direct Giving",
}

# (group key, categories folded into it, heading, blurb) — five raw
# categories collapse into two visible sections plus a "direct" closing
# band (handled separately below) so the page reads as three balanced
# groups instead of five sparse ones; each card still carries its own
# specific category badge (see FUNDRAISER_CATEGORY_LABELS) so nothing
# about that grouping is lost.
FUNDRAISER_GROUPS = [
    (
        ["recurring", "seasonal", "annual"],
        "Every Year",
        "Traditional Campaigns",
        "Dated and seasonal fundraisers the PTA runs every year — some are happening now, some are still to come.",
    ),
    (
        ["everyday"],
        "All Year Long",
        "Everyday Giving",
        "Set these up once and they keep giving all year long, at no extra cost to you.",
    ),
]


def render_fundraiser_card(campaign, context):
    """One fundraising campaign's card. Two shapes depending on the data:
    a dated campaign (Restaurant Nights) shows its date list directly in
    the always-visible summary — the dates *are* how a family joins, so
    unlike the afterschool-program card's <details> pattern, nothing
    essential is hidden behind a click here. An undated campaign (a
    storefront, an everyday-giving program) shows its "how to join" line
    and CTA button(s) instead. A flyer or contact, when present, still
    goes in a <details> "Details" disclosure — same reasoning as
    render_afterschool_program_card, for whichever field doesn't need to
    be seen immediately."""
    category = campaign["category"]
    parts = [
        f'<span class="thes__badge thes__badge--fund-{category}">{FUNDRAISER_CATEGORY_LABELS[category]}</span>',
        f'<h3>{campaign["name"]}</h3>',
        f'<p>{campaign["description"]}</p>',
    ]

    dates = campaign.get("dates") or []
    if dates:
        rows = []
        for d in dates:
            note = f'<p class="thes__fund-date-note">{d["note"]}</p>' if d.get("note") else ""
            rows.append(
                f'<li><strong>{d["date"]}</strong> — {d["venue"]}, {d["time"]}{note}</li>'
            )
        parts.append(f'<ul class="thes__fund-dates">{"".join(rows)}</ul>')

    if campaign.get("how_to_join"):
        parts.append(f'<p class="thes__fund-howto">{campaign["how_to_join"]}</p>')

    if campaign.get("enrollment_code"):
        parts.append(f'<p class="thes__fund-code">Enrollment code: <strong>{campaign["enrollment_code"]}</strong></p>')

    buttons = []
    if campaign.get("cta_href"):
        buttons.append(
            f'<a class="thes__btn thes__btn--teal" href="{campaign["cta_href"]}" target="_blank" rel="noopener">'
            f'{campaign["cta_label"]} &rarr;</a>'
        )
    secondary_href = campaign.get("secondary_href")
    if secondary_href:
        # A JSON value of "page_urls.xxx" is a sentinel meaning "resolve
        # this as an internal link" — context already holds it fully
        # resolved (relative filename, right "../" depth) under that
        # same dotted key, same as any {{page_urls.xxx}} used directly in
        # a template. Every other value is a literal external URL.
        if secondary_href.startswith("page_urls."):
            secondary_href = context[secondary_href]
            buttons.append(f'<a class="thes__btn thes__btn--navy" href="{secondary_href}">{campaign["secondary_label"]} &rarr;</a>')
        else:
            buttons.append(
                f'<a class="thes__btn thes__btn--navy" href="{secondary_href}" target="_blank" rel="noopener">'
                f'{campaign["secondary_label"]} &rarr;</a>'
            )
    if buttons:
        parts.append('<div class="thes__fund-actions">' + "".join(buttons) + "</div>")

    details = []
    flyer_filename = campaign.get("flyer_filename")
    if flyer_filename:
        flyer_url = f'{context["FLYER_BASE_URL"]}/fundraising/{flyer_filename}'
        details.append(
            f'<a class="thes__flyer" href="{flyer_url}" target="_blank" rel="noopener">'
            f'<img src="{flyer_url}" alt="" width="160" loading="lazy">'
            f'<span>{ATTACHMENT_LINK_TEXT}</span></a>'
        )
    if campaign.get("contact"):
        details.append(f'<p>{campaign["contact"]}</p>')

    details_html = ""
    if details:
        details_html = (
            '<details class="thes__program-more"><summary>Details</summary>'
            f'<div class="thes__program-more-body">{"".join(details)}</div></details>'
        )

    return f'<div class="thes__fund-card">{"".join(parts)}{details_html}</div>'


def build_fundraising_section(campaigns, context):
    """Whole Fundraising page body: campaigns grouped into a couple of
    visually-balanced sections (see FUNDRAISER_GROUPS) plus a closing
    full-width "Give Directly" band — a single-card grid for a one-entry
    category would read as sparse, so it gets the same treatment as
    committees.html's "Not Sure Where to Help?" closer instead. Same
    empty-means-a-placeholder-message pattern as the other always-in-nav
    pages (afterschool programs, events)."""
    if not campaigns:
        return (TEMPLATES / "fundraising-empty.html.tmpl").read_text()

    by_category = {}
    for c in campaigns:
        by_category.setdefault(c["category"], []).append(c)
    direct = by_category.pop("direct", [])

    sections = []
    tint = True

    # "Give Directly" leads the page — the most immediate, no-research-
    # needed way to help, ahead of the other campaigns that each take a
    # minute to read and act on. Only the first "direct" entry (money,
    # via Donate Now) gets the big single-CTA band treatment — any
    # further ones (e.g. an in-kind item wish list) are a different
    # *kind* of direct giving, not another way to give money, so they
    # get their own card(s) in a grid right below the band instead of
    # competing with it for the same treatment.
    if direct:
        d = direct[0]
        sections.append(
            f'<section class="thes__section {"thes__section--tint" if tint else ""}">\n'
            '  <div class="thes__wrap">\n'
            '    <div class="thes__join">\n'
            f'      <h2>{d["name"]}</h2>\n'
            f'      <p>{d["description"]}</p>\n'
            f'      <a class="thes__btn thes__btn--navy" href="{d["cta_href"]}" target="_blank" rel="noopener">{d["cta_label"]} &rarr;</a>\n'
            "    </div>\n"
            "  </div>\n"
            "</section>"
        )
        tint = not tint

        extra_direct = direct[1:]
        if extra_direct:
            cards = "\n".join(indent(render_fundraiser_card(c, context), 6) for c in extra_direct)
            section_class = "thes__section thes__section--tint" if tint else "thes__section"
            sections.append(
                f'<section class="{section_class}">\n'
                '  <div class="thes__wrap">\n'
                '    <div class="thes__fund-grid">\n'
                f"{cards}\n"
                "    </div>\n"
                "  </div>\n"
                "</section>"
            )
            tint = not tint

    for categories, eyebrow, heading, blurb in FUNDRAISER_GROUPS:
        group_campaigns = [c for cat in categories for c in by_category.get(cat, [])]
        if not group_campaigns:
            continue
        cards = "\n".join(indent(render_fundraiser_card(c, context), 6) for c in group_campaigns)
        section_class = "thes__section thes__section--tint" if tint else "thes__section"
        sections.append(
            f'<section class="{section_class}">\n'
            '  <div class="thes__wrap">\n'
            '    <div class="thes__section-head">\n'
            f'      <span class="thes__eyebrow">{eyebrow}</span>\n'
            f'      <h2>{heading}</h2>\n'
            f"      <p>{blurb}</p>\n"
            "    </div>\n"
            '    <div class="thes__fund-grid">\n'
            f"{cards}\n"
            "    </div>\n"
            "  </div>\n"
            "</section>"
        )
        tint = not tint

    return "\n\n".join(sections)


def compute_school_year(date_str):
    """'2026-09-08' -> '2026–2027'. A school year is treated as running
    July through the following June, so a meeting in, say, April groups
    with the September that started that same school year rather than
    the following one — this is why the boundary is July (month >= 7),
    not January."""
    d = dt.date.fromisoformat(date_str)
    start_year = d.year if d.month >= 7 else d.year - 1
    return f"{start_year}–{start_year + 1}"


UPCOMING_PTA_MEETINGS_MAX = 3


def build_hcpss_events_section(events, context):
    """The "Upcoming Events" list at the top of the Special Education &
    Family Support page, above its live calendar embed — sourced from
    config/hcpss-family-events.json, synced from HCPSS's own Special
    Education Parent & Guardian Calendar (scripts/sync_hcpss_calendar.py)
    — a completely separate calendar from the PTA's own
    config/events.json, already capped to the next 3 occurrences at
    generation time (no redundant re-capping here — same
    trust-the-generator approach the Events page takes with
    config/events.json). Reuses event-row.html.tmpl as-is, same as the
    Events page and the PTA Meetings page's own "Upcoming" section. ""
    when HCPSS's calendar has nothing upcoming right now, same
    empty-means-no-section pattern as everywhere else on the site."""
    if not events:
        return ""
    row_tmpl = (TEMPLATES / "event-row.html.tmpl").read_text()
    rows = "\n".join(indent(render(row_tmpl, {**context, **with_event_extras(e)}), 6) for e in events)
    return (
        '<section class="thes__section thes__section--tint">\n'
        '  <div class="thes__wrap">\n'
        '    <div class="thes__section-head">\n'
        "      <h2>Upcoming Events</h2>\n"
        "      <p>The next few workshops and events on HCPSS's calendar.</p>\n"
        "    </div>\n"
        '    <div class="thes__event-list">\n'
        f"{rows}\n"
        "    </div>\n"
        "  </div>\n"
        "</section>"
    )


def build_upcoming_pta_meetings_section(upcoming_meetings, context):
    """The top-of-page 'what's coming up' section on the PTA Meetings
    page — sourced live from config/pta-meeting-occurrences.json
    (generated from Google Calendar by
    scripts/sync_calendar_events.py, never hand-edited). Deliberately a
    *separate* generated file from config/events.json, not a filter over
    it: events.json is capped at MAX_EVENTS (6) across every event type
    on the calendar for the Home/Events page highlights, so a PTA
    meeting further out than the 6th nearest calendar-wide event would
    never have reached this section at all if it were just filtering
    events.json — caught for real when a real Feb 2027 meeting was
    invisible here despite being well within the general lookahead
    window, crowded out by nearer restaurant nights and a fall festival.

    Deliberately separate from the rest of the page (the permanent
    post-meeting archive in config/pta-meetings.json, filled in from a
    recap flyer after a meeting happens): this section shows what's
    ahead, the rest of the page shows what already happened. Reuses
    event-row.html.tmpl as-is (day/month/title/when/description/Sign Up
    or Join Google Meet buttons/attachments) — the exact same row
    already used on the Events page, so a meeting that has, say, a
    Google Meet link on the calendar gets that button here too. ""
    when there's no upcoming PTA meeting on the calendar right now, same
    empty-means-no-section pattern as everywhere else on the site.
    Capped at UPCOMING_PTA_MEETINGS_MAX (3) — config/pta-meeting-
    occurrences.json is already date-ascending (see
    scripts/sync_calendar_events.py), so this is simply the next 3
    chronologically, same capped-preview pattern
    build_home_events_section uses."""
    upcoming = upcoming_meetings[:UPCOMING_PTA_MEETINGS_MAX]
    if not upcoming:
        return ""
    row_tmpl = (TEMPLATES / "event-row.html.tmpl").read_text()
    rows = "\n".join(indent(render(row_tmpl, {**context, **with_event_extras(e)}), 6) for e in upcoming)
    return (
        '<section class="thes__section">\n'
        '  <div class="thes__wrap">\n'
        '    <div class="thes__section-head">\n'
        "      <h2>Upcoming PTA Meetings</h2>\n"
        "      <p>From the PTA calendar — join us live, or check back here afterward for the recap.</p>\n"
        "    </div>\n"
        '    <div class="thes__event-list">\n'
        f"{rows}\n"
        "    </div>\n"
        "  </div>\n"
        "</section>"
    )


def render_meeting_flyer(meeting, context):
    """A meeting's recap-graphic flyer, if it has one — same
    small-thumbnail-plus-link treatment every other flyer type on the
    site uses. "" when there's no flyer, same optional-field pattern as
    everywhere else."""
    flyer_filename = meeting.get("flyer_filename")
    if not flyer_filename:
        return ""
    flyer_url = f'{context["FLYER_BASE_URL"]}/pta-meetings/{flyer_filename}'
    return (
        f'<a class="thes__flyer" href="{flyer_url}" target="_blank" rel="noopener">'
        f'<img src="{flyer_url}" alt="" width="160" loading="lazy">'
        f"<span>{ATTACHMENT_LINK_TEXT}</span></a>"
    )


def render_pta_meeting_card(meeting, context):
    """One PTA meeting's compact archive card (card-pta-meeting.html.tmpl)
    — date, title, highlights, flyer (if any), and a "View Agenda"
    button. Used for every meeting except whichever one is currently
    spotlighted at the top of the page (see build_pta_meetings_section)."""
    d = dt.date.fromisoformat(meeting["date"])
    date_display = d.strftime("%B %-d, %Y")
    agenda_button = ""
    if meeting.get("agenda_href"):
        agenda_button = (
            f'<a class="thes__btn thes__btn--teal" href="{meeting["agenda_href"]}" '
            f'target="_blank" rel="noopener">View Agenda &rarr;</a>'
        )
    tmpl = (TEMPLATES / "card-pta-meeting.html.tmpl").read_text()
    return render(tmpl, {
        **meeting, "date_display": date_display, "AGENDA_BUTTON": agenda_button,
        "FLYER": render_meeting_flyer(meeting, context),
    })


def render_featured_pta_meeting(meeting, context):
    """The single most recent meeting, spotlighted above the year
    archive — reuses .thes__featured-event, the same navy-card treatment
    (and the same fixed-width, centered-text button rule) the Home
    page's featured event already uses, for a consistent "here's the one
    that matters most right now" visual language across the site."""
    d = dt.date.fromisoformat(meeting["date"])
    date_display = d.strftime("%B %-d, %Y")
    agenda_button = ""
    if meeting.get("agenda_href"):
        agenda_button = (
            f'<a class="thes__btn thes__btn--teal" href="{meeting["agenda_href"]}" '
            f'target="_blank" rel="noopener">View Agenda &rarr;</a>'
        )
    tmpl = (TEMPLATES / "pta-meeting-featured.html.tmpl").read_text()
    return render(tmpl, {
        **meeting, "date_display": date_display, "AGENDA_BUTTON": agenda_button,
        "FLYER": render_meeting_flyer(meeting, context),
    })


def build_pta_meetings_section(meetings, upcoming_meetings, context):
    """Whole PTA Meetings page body: an "Upcoming PTA Meetings" section
    sourced live from the calendar (see build_upcoming_pta_meetings_section)
    first, then the single most recent *reviewed* past meeting spotlighted,
    then every other reviewed meeting grouped into a <details> accordion
    per school year (most recent year already open, older years collapsed
    — same zero-JS expand/collapse pattern committees/afterschool-program
    cards already use).

    "Reviewed" matters here in a way it doesn't for the other flyer
    types: a brand-new flyer's placeholder (see
    scripts/sync_pta_meeting_flyers.py) has `date: None` on purpose —
    guessing a date the way the other syncs guess a *name* would risk
    silently misfiling the meeting into the wrong school year until
    someone caught it, which is worse than just not showing it in the
    dated archive at all. Meetings without a date can't be sorted or
    grouped, so they're split out into their own "flagged for review"
    notice instead — and specifically never allowed to become the
    spotlight card, since an unreviewed placeholder has no real content
    to spotlight.

    Same empty-means-a-placeholder-message pattern as the other
    always-in-nav pages for the true empty case (nothing recorded at
    all, reviewed or not) — the upcoming section still renders on top of
    that placeholder if the calendar has a meeting coming up."""
    sections = []

    upcoming_section = build_upcoming_pta_meetings_section(upcoming_meetings, context)
    if upcoming_section:
        sections.append(upcoming_section)

    if not meetings:
        sections.append((TEMPLATES / "pta-meetings-empty.html.tmpl").read_text())
        return "\n\n".join(sections)

    reviewed = [m for m in meetings if m.get("date")]
    pending = [m for m in meetings if not m.get("date")]

    if pending:
        names = ", ".join(m.get("flyer_filename", "a flyer") for m in pending)
        sections.append(
            '<section class="thes__section thes__section--tint">\n'
            '  <div class="thes__wrap">\n'
            f'    <p class="thes__committees-note">{len(pending)} new meeting flyer'
            f'{"s" if len(pending) != 1 else ""} ({names}) '
            "need review before showing up here with real details.</p>\n"
            "  </div>\n"
            "</section>"
        )

    if not reviewed:
        return "\n\n".join(sections) if sections else (TEMPLATES / "pta-meetings-empty.html.tmpl").read_text()

    ordered = sorted(reviewed, key=lambda m: m["date"], reverse=True)
    latest, rest = ordered[0], ordered[1:]

    sections.append(
        '<section class="thes__section">\n'
        '  <div class="thes__wrap thes__meetings-featured-wrap">\n'
        f"{indent(render_featured_pta_meeting(latest, context), 4)}\n"
        "  </div>\n"
        "</section>"
    )

    if rest:
        by_year = {}
        for m in rest:
            by_year.setdefault(compute_school_year(m["date"]), []).append(m)

        year_blocks = []
        for i, year in enumerate(sorted(by_year.keys(), reverse=True)):
            cards = "\n".join(indent(render_pta_meeting_card(m, context), 8) for m in by_year[year])
            open_attr = " open" if i == 0 else ""
            year_blocks.append(
                f'<details class="thes__year-group"{open_attr}>\n'
                f"  <summary>{year}</summary>\n"
                '  <div class="thes__meeting-grid">\n'
                f"{cards}\n"
                "  </div>\n"
                "</details>"
            )

        sections.append(
            '<section class="thes__section thes__section--tint">\n'
            '  <div class="thes__wrap">\n'
            '    <div class="thes__section-head">\n'
            "      <h2>Past Meetings</h2>\n"
            "      <p>Browse previous meetings by school year.</p>\n"
            "    </div>\n"
            f"{indent(chr(10).join(year_blocks), 4)}\n"
            "  </div>\n"
            "</section>"
        )

    return "\n\n".join(sections)


def build_analytics_snippet(ga_id):
    """Google Analytics 4's standard gtag.js snippet for config/site.json's
    `google_analytics_id`, placed immediately after <head> opens on every
    page (Google's own installation instructions specifically call out
    this exact position). Returns "" (nothing rendered, no third-party
    script at all) when it's blank — this ships with zero tracking until
    a real Measurement ID is configured. flatten() stringifies every
    context value, so this also guards against the literal string "None"
    a JSON `null` would otherwise produce here — use "" in config, not
    null, to turn this off."""
    if not ga_id or ga_id == "None":
        return ""
    return (
        "<!-- Google tag (gtag.js) -->\n"
        f'<script async src="https://www.googletagmanager.com/gtag/js?id={ga_id}"></script>\n'
        "<script>\n"
        "  window.dataLayer = window.dataLayer || [];\n"
        "  function gtag(){dataLayer.push(arguments);}\n"
        "  gtag('js', new Date());\n"
        f"  gtag('config', '{ga_id}');\n"
        "</script>\n"
    )


def build_umami_snippet(website_id):
    """Umami Cloud's standard tracking snippet for config/site.json's
    `umami_website_id`, run alongside (not instead of) Google Analytics —
    they're independent script tags with no interaction, so both can
    track the same visitor with no conflict. Returns "" (no script at
    all) when blank, same empty-means-off pattern as
    build_analytics_snippet."""
    if not website_id or website_id == "None":
        return ""
    return f'<script defer src="https://cloud.umami.is/script.js" data-website-id="{website_id}"></script>\n'


def build_organization_jsonld(site):
    """schema.org Organization structured data, embedded as JSON-LD on
    every page — this is the machine-readable version of "who is this
    website" that Google's Knowledge Graph and an AI assistant grounding
    an answer in search results both look for, distinct from (and more
    reliable than) either one inferring the same facts by reading prose.
    Built from config/site.json's existing fields — nothing new to
    maintain here if the address, email, or social links ever change.

    address_line2 is free text ("Columbia, MD 21045") rather than
    separate city/state/zip fields in config/site.json, since that's the
    only place on the actual pages this address is ever split apart —
    parsed best-effort here into addressLocality/addressRegion/
    postalCode for schema.org's PostalAddress shape, falling back to
    putting the whole line in addressLocality if it doesn't match the
    expected "City, ST 12345" pattern rather than raising or guessing."""
    address = {"@type": "PostalAddress", "streetAddress": site.get("address_line1", "")}
    line2 = site.get("address_line2", "")
    m = re.match(r"^\s*(.+?),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)\s*$", line2)
    if m:
        address["addressLocality"] = m.group(1)
        address["addressRegion"] = m.group(2)
        address["postalCode"] = m.group(3)
    elif line2:
        address["addressLocality"] = line2
    address["addressCountry"] = "US"

    data = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": site.get("org_name", ""),
        "url": f'https://{site["custom_domain"]}/',
        "logo": f'https://{site["custom_domain"]}/images/{site["hero_image_filename"]}',
        "email": site.get("email", ""),
        "address": address,
        "sameAs": [href for href in site.get("social", {}).values() if href],
    }
    return f'<script type="application/ld+json">{json.dumps(data)}</script>\n'


def colorize_title_words(text):
    """Alternate each word's color between the site's dark text tone and
    teal — the same two-tone treatment already used in the home hero
    image's headline ("Stronger Together." / "Better for Every Student.")
    — applied here to the live <h1> text on every other page's header."""
    classes = ["thes__title-a", "thes__title-b"]
    words = text.split(" ")
    return " ".join(f'<span class="{classes[i % 2]}">{w}</span>' for i, w in enumerate(words))


PAGE_TITLES = {
    "about.html": "Who We Are",
    "get-involved.html": "Join Us",
    "events.html": "Upcoming Events",
    "newsletter.html": "Newsletters",
    "newsletter/thes-happenings.html": "THES Official Newsletter (THES Happenings)",
    "newsletter/pta-newsletter.html": "PTA Newsletter",
    "get-involved/committees.html": "Committees",
    "before-after-school-programs.html": "Before & After School Programs",
    "shop.html": "Shop",
    "fundraising.html": "Ways to Give",
    "pta-meetings.html": "PTA Meetings",
    "family-support-resources.html": "Family Support Resources",
    "family-support-resources/special-education-family-support.html": "Special Education & Family Support",
    "family-support-resources/student-parent-handbook.html": "HCPSS Student & Parent Handbook",
}

# One line per page for <meta name="description"> — this is the summary
# a search engine (and an AI assistant grounding an answer in search
# results) actually quotes back, so it's worth writing by hand rather
# than deriving it from PAGE_TITLES. Falls back to the home page's own
# description for any page not listed here (see main()) rather than
# shipping a page with no description at all.
PAGE_DESCRIPTIONS = {
    "index.html": (
        "The official website of the Thunder Hill Elementary PTA (THES PTA) in "
        "Columbia, MD — events, PTA meetings, volunteering, and fundraising, all "
        "in one place."
    ),
    "about.html": (
        "Meet the Thunder Hill Elementary PTA Executive Board and learn about our "
        "mission to support students, staff, and families at THES."
    ),
    "get-involved.html": (
        "Volunteer opportunities, committees, and membership information for the "
        "Thunder Hill Elementary PTA — find out how to get involved at THES."
    ),
    "events.html": (
        "See every upcoming Thunder Hill Elementary PTA event, synced live from "
        "our calendar — meetings, fundraisers, and school-wide celebrations."
    ),
    "newsletter.html": (
        "Two ways to keep up with Thunder Hill Elementary — the school's own "
        "newsletter and the PTA's own newsletter."
    ),
    "newsletter/thes-happenings.html": (
        "Read THES Happenings, Thunder Hill Elementary's official newsletter, "
        "for the latest news and updates from our school community."
    ),
    "newsletter/pta-newsletter.html": (
        "The Thunder Hill Elementary PTA's own newsletter — PTA news and "
        "celebrations."
    ),
    "get-involved/committees.html": (
        "Browse Thunder Hill Elementary PTA committees and find the one that "
        "matches your interests and availability."
    ),
    "before-after-school-programs.html": (
        "Before and after school enrichment programs available at Thunder Hill "
        "Elementary School, with schedules and pricing."
    ),
    "shop.html": "Shop Thunder Hill Elementary spirit wear and support the THES PTA.",
    "fundraising.html": (
        "Ways to give to the Thunder Hill Elementary PTA — membership, donations, "
        "and fundraisers that support our students and teachers."
    ),
    "pta-meetings.html": (
        "Highlights, agendas, and recaps from every Thunder Hill Elementary PTA "
        "meeting, archived by school year."
    ),
    "family-support-resources.html": (
        "Howard County and community resources for Thunder Hill Elementary "
        "families, beyond what the PTA runs directly."
    ),
    "family-support-resources/special-education-family-support.html": (
        "HCPSS's Special Education Parent & Guardian Calendar and Family "
        "Support and Resource Center — events and workshops for families of "
        "students with an IEP/IFSP."
    ),
    "family-support-resources/student-parent-handbook.html": (
        "HCPSS's Student and Parent Handbook — school system practices, "
        "policies, and support services for every Howard County family."
    ),
}


def main():
    # These don't depend on page depth (no internal page_urls/image
    # links of their own), so they're built once and reused for whatever
    # page(s) actually reference them — same as before this file
    # supported nested pages at all.
    board_cards = build_board_cards()
    events = load_json("events.json", default=[])
    hcpss_events = load_json("hcpss-family-events.json", default=[])
    site = load_json("site.json")
    committees_section = build_committees_section(
        load_json("committees.json", default=[]), site["volunteerForm"]
    )
    welcome_video_section = build_welcome_video_section(site)
    organization_jsonld = build_organization_jsonld(site)

    page_templates = sorted((TEMPLATES / "pages").rglob("*.html.tmpl"))
    if not page_templates:
        raise SystemExit("No page templates found in src/templates/pages/")

    PAGES_OUT.mkdir(exist_ok=True)
    context_by_depth = {}
    built_page_names = []

    for tmpl_path in page_templates:
        rel = tmpl_path.relative_to(TEMPLATES / "pages")
        depth = len(rel.parts) - 1
        page_name = str(rel).removesuffix(".tmpl")

        # Everything that depends on page_urls.*/HERO_IMAGE_URL/etc has to
        # be rebuilt per depth — a page one directory down needs "../"
        # prefixes a top-level page doesn't. Cheap to just rebuild (this
        # site has a handful of pages total) and memoizing per depth
        # avoids redoing it once per page at the same depth.
        if depth not in context_by_depth:
            context_by_depth[depth] = build_context(depth)
        context = context_by_depth[depth]
        tokens = build_tokens(context)
        header = build_header(context)
        footer = build_footer(context)
        home_events_section = build_home_events_section(events, context)
        events_page_section = build_events_page_section(events, context)
        sponsors_section = build_optional_section(
            "sponsors.json", "card-sponsor.html.tmpl", "sponsors-section.html.tmpl", "SPONSOR_CARDS", context
        )
        flyers_section = build_optional_section(
            "flyers.json", "card-flyer.html.tmpl", "flyers-section.html.tmpl", "FLYER_CARDS", context
        )
        fundraising_section = build_fundraising_section(
            load_json("fundraisers.json", default=[]), context
        )
        afterschool_programs_section = build_afterschool_programs_section(
            load_json("afterschool-programs.json", default=[]), context
        )
        pta_meetings_section = build_pta_meetings_section(
            load_json("pta-meetings.json", default=[]),
            load_json("pta-meeting-occurrences.json", default=[]),
            context,
        )
        family_support_resources_section = build_family_support_resources_section(
            load_json("family-support-resources.json", default=[]), context
        )
        hcpss_events_section = build_hcpss_events_section(hcpss_events, context)

        shared_markers = {
            "{{TOKENS}}": tokens,
            "{{FOOTER}}": footer,
            "{{BOARD_CARDS}}": board_cards,
            "{{EVENTS_SECTION}}": home_events_section,
            "{{EVENTS_LIST_SECTION}}": events_page_section,
            "{{SPONSORS_SECTION}}": sponsors_section,
            "{{FLYERS_SECTION}}": flyers_section,
            "{{COMMITTEES_SECTION}}": committees_section,
            "{{WELCOME_VIDEO_SECTION}}": welcome_video_section,
            "{{AFTERSCHOOL_PROGRAMS_SECTION}}": afterschool_programs_section,
            "{{FUNDRAISING_SECTIONS}}": fundraising_section,
            "{{PTA_MEETINGS_SECTION}}": pta_meetings_section,
            "{{FAMILY_SUPPORT_RESOURCES_SECTION}}": family_support_resources_section,
            "{{HCPSS_EVENTS_SECTION}}": hcpss_events_section,
        }

        page_context = context
        if page_name in PAGE_TITLES:
            page_context = {**context, "PAGE_TITLE": colorize_title_words(PAGE_TITLES[page_name])}
        text = tmpl_path.read_text()
        text = render(text, page_context)
        for marker, value in shared_markers.items():
            text = text.replace(marker, value)

        # Decoupled from each page template's own markup on purpose: the
        # header is inserted structurally right after `<div class="thes">`
        # opens, rather than relying on a `{{HEADER}}` marker every page
        # template has to remember to include. A real page once shipped
        # without one (copied from before this branch had a header at
        # all) because nothing enforced its presence — this makes it
        # impossible for any current or future page to omit it.
        text = text.replace('<div class="thes">', f'<div class="thes">\n{header}', 1)

        leftover = PLACEHOLDER.findall(text)
        if leftover:
            print(f"  ! {page_name}: unresolved placeholder(s): {sorted(set(leftover))}")

        # These pages are opened directly (no Google Sites parent page to
        # supply a <head>/viewport for them), so this is a real document
        # shell, not a fragment. Missing the viewport meta specifically
        # would silently break any @media query meant for phones — without
        # it, mobile browsers assume a fake ~980px desktop-width layout
        # viewport instead of the device's real width.
        # index.html is the home page (named that so it loads automatically
        # at the domain root) but should still say "Home" in the browser
        # tab, not the literal filename. For any other page, use just the
        # last path segment (Path.stem) as the title base, ignoring any
        # parent directories — "get-involved/committees.html" should say
        # "Committees", not "Get-Involved/Committees".
        page_title = "Home" if page_name == "index.html" else Path(page_name).stem.replace("-", " ").title()
        analytics_snippet = build_analytics_snippet(context.get("google_analytics_id", ""))
        analytics_snippet += build_umami_snippet(context.get("umami_website_id", ""))
        page_description = PAGE_DESCRIPTIONS.get(page_name, PAGE_DESCRIPTIONS["index.html"])
        canonical_url = f'https://{site["custom_domain"]}/{"" if page_name == "index.html" else page_name}'
        text = (
            "<!DOCTYPE html>\n"
            '<html lang="en">\n<head>\n'
            f"{analytics_snippet}"
            '<meta charset="UTF-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<meta name="description" content="{page_description}">\n'
            f'<link rel="canonical" href="{canonical_url}">\n'
            f"<title>{context.get('org_name', '')} — {page_title}</title>\n"
            f"{organization_jsonld}"
            f"</head>\n<body>\n{text}\n</body>\n</html>\n"
        )

        out_path = PAGES_OUT / page_name
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text)
        built_page_names.append(page_name)
        print(f"  built {out_path.relative_to(ROOT)}")

    # GitHub Pages' custom-domain feature reads a plain-text CNAME file
    # (just the domain, nothing else) from the deployed site's root.
    # Generated from config/site.json's `custom_domain` — the single
    # source of truth — rather than hand-maintained separately, so it
    # can never drift out of sync with what the site actually claims to
    # be. .github/workflows/deploy.yml copies this into site/ alongside
    # pages/*.html and assets/images/*.
    custom_domain = load_json("site.json").get("custom_domain")
    if custom_domain:
        (PAGES_OUT / "CNAME").write_text(custom_domain + "\n")
        print(f"  built {(PAGES_OUT / 'CNAME').relative_to(ROOT)} ({custom_domain})")

    # sitemap.xml + robots.txt, generated from the same page list every
    # other per-page thing above was built from — same "never hand-
    # maintain a thing that can drift" reasoning as the CNAME file just
    # above. This deliberately always writes the *real* domain and an
    # allow-everything robots.txt, correct for production; the staging
    # mirror (thespta-prestage) overwrites robots.txt with a blanket
    # disallow in its own deploy.yml, right before the deploy step — see
    # that workflow file for why staging must never be indexed even
    # though it's built from this exact same code.
    if custom_domain:
        sitemap_urls = "\n".join(
            f"  <url><loc>https://{custom_domain}/{'' if name == 'index.html' else name}</loc></url>"
            for name in built_page_names
        )
        sitemap = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{sitemap_urls}\n"
            "</urlset>\n"
        )
        (PAGES_OUT / "sitemap.xml").write_text(sitemap)
        print(f"  built {(PAGES_OUT / 'sitemap.xml').relative_to(ROOT)} ({len(built_page_names)} URLs)")

        # Explicitly naming the AI-assistant crawlers alongside the
        # wildcard is redundant with "User-agent: *" but deliberate: it
        # makes it obvious at a glance (to a human reading this file, or
        # to a platform that greps robots.txt for its own bot's name
        # specifically) that this site was intentionally opened up to
        # them, not just left at whatever the wildcard default happened
        # to allow.
        robots_txt = (
            "User-agent: *\n"
            "Allow: /\n"
            "\n"
            "User-agent: GPTBot\n"
            "Allow: /\n"
            "\n"
            "User-agent: ChatGPT-User\n"
            "Allow: /\n"
            "\n"
            "User-agent: ClaudeBot\n"
            "Allow: /\n"
            "\n"
            "User-agent: anthropic-ai\n"
            "Allow: /\n"
            "\n"
            "User-agent: Google-Extended\n"
            "Allow: /\n"
            "\n"
            "User-agent: PerplexityBot\n"
            "Allow: /\n"
            "\n"
            "User-agent: CCBot\n"
            "Allow: /\n"
            "\n"
            f"Sitemap: https://{custom_domain}/sitemap.xml\n"
        )
        (PAGES_OUT / "robots.txt").write_text(robots_txt)
        print(f"  built {(PAGES_OUT / 'robots.txt').relative_to(ROOT)}")

    print(f"\nDone — {len(page_templates)} pages written to /pages.")
    print("Push to main to deploy — GitHub Actions rebuilds, validates, and redeploys to GitHub Pages automatically.")


if __name__ == "__main__":
    main()
