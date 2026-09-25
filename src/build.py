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
import hashlib
import html
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


def site_today(site):
    """Today's date in the PTA's own timezone (config/site.json's
    calendar.timezone), not the machine's — GitHub Actions runners are on
    UTC, which would otherwise flip to "tomorrow" at 8 PM Eastern and
    expire an announcement or event page hours early on its last day."""
    from zoneinfo import ZoneInfo

    return dt.datetime.now(ZoneInfo(site["calendar"]["timezone"])).date()


def is_expired(expires, today):
    """True once `today` is past an ISO `expires` date ("YYYY-MM-DD") —
    `expires` is the *last day* something is shown, inclusive. A missing
    or malformed value never expires (shown until removed by hand) rather
    than silently vanishing on a typo."""
    if not expires:
        return False
    try:
        return dt.date.fromisoformat(expires) < today
    except ValueError:
        return False


def event_page_expires(event):
    """A featured event page's `expires` date — its own explicit one if
    set, otherwise the day the event ends (so it disappears the morning
    after)."""
    if event.get("expires"):
        return event["expires"]
    return dt.datetime.fromisoformat(event.get("end") or event["start"]).date().isoformat()


def load_active_event_pages(site):
    """Entries in config/event-pages.json that haven't expired yet. The
    hourly/push pipelines normally move expired ones out to archive/ via
    scripts/archive_expired.py before building, but the build filters
    them too, so a local build (or a pipeline run that hasn't archived
    yet) never publishes an expired page either."""
    today = site_today(site)
    return [e for e in load_json("event-pages.json", default=[]) if not is_expired(event_page_expires(e), today)]


def event_page_url_key(event):
    return "event_" + re.sub(r"\W", "_", event["slug"])


def load_site():
    """config/site.json, plus one page_urls entry and one Events-menu
    child per active featured event page — so each featured event shows
    up under Events in the nav (and gets breadcrumbs / "you are here"
    highlighting) automatically, sorted by date, and drops out of the
    menu the moment it expires, with no hand-edit of the nav needed
    either way. Every place that needs the nav or page_urls reads
    through this rather than site.json directly."""
    site = load_json("site.json")
    event_pages = sorted(load_active_event_pages(site), key=lambda e: e["start"])
    if not event_pages:
        return site
    page_urls = site.setdefault("page_urls", {})
    for e in event_pages:
        page_urls[event_page_url_key(e)] = event_page_name(e).removesuffix(".html")
    for item in site.get("nav", []):
        if item.get("page_url") == "events":
            item["children"] = (item.get("children") or []) + [
                {"label": html.escape(e.get("nav_label") or e["title"]), "page_url": event_page_url_key(e)}
                for e in event_pages
            ]
            break
    return site


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
    site = load_site()
    theme = load_json("theme.json")

    context = flatten(site)
    context["font_display"] = theme["fonts"]["display"]
    context["font_body"] = theme["fonts"]["body"]
    context["google_fonts_url"] = theme["fonts"]["google_fonts_url"]
    context.update(flatten(theme["colors"], "colors"))

    prefix = "../" * depth

    # Served by GitHub Pages alongside the HTML — see .github/workflows/deploy.yml,
    # which copies assets/images/* into site/images/ next to pages/*.html.
    context["IMAGES_BASE_URL"] = f"{prefix}images"
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
    # Home links to the site root ("./" or "../"), not index.html — the
    # root is the canonical URL, and linking to index.html is how Google
    # kept finding it as a duplicate ("Alternate page with proper
    # canonical tag" in Search Console).
    if "page_urls.home" in context:
        context["page_urls.home"] = prefix or "./"

    context["ADDRESS_LINE2_LONG"] = site_address_line2_long(site)

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


def render_nav_items(items, context, current_page_url=None):
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
    inline style always wins the cascade.

    `current_page_url` is the `page_urls.*` key of the page actually
    being built (see main()'s PAGE_URL_KEYS_BY_NAME) — used to mark
    "you are here" in the nav: the matching item/child gets
    `aria-current="page"` and a `thes__nav-link--current` class, and a
    parent whose *child* is current also gets that class on its own
    trigger (not aria-current, since the parent itself isn't the current
    page) so a visitor on, say, the Committees page can see at a glance
    that it's "Get Involved" they'd click to go back up. Every rule this
    adds combines with an element+class selector (see
    .thes__header-nav a.thes__nav-link--current in tokens.html.tmpl) —
    a bare single-class rule would lose to `.thes a { color: inherit; }`
    the same way the navy-button bug did (see "Hard-won constraints" in
    CLAUDE.md)."""
    html = []
    for i, item in enumerate(items):
        label = item["label"]
        href = context[f"page_urls.{item['page_url']}"] if item.get("page_url") else None
        children = item.get("children")
        is_current = current_page_url is not None and item.get("page_url") == current_page_url
        if children:
            child_is_current = [c.get("page_url") == current_page_url for c in children]
            is_active_parent = is_current or any(child_is_current)
            submenu_id = f"thes-submenu-{i}"
            child_html = "".join(
                '<li><a href="{}"{}>{}</a></li>'.format(
                    context[f'page_urls.{c["page_url"]}'],
                    ' class="thes__nav-link--current" aria-current="page"' if is_c else "",
                    c["label"],
                )
                for c, is_c in zip(children, child_is_current)
            )
            trigger_attrs = ' class="thes__nav-link--current"' if is_active_parent else ""
            trigger = f'<a href="{href}"{trigger_attrs}>{label}</a>' if href else f'<span class="thes__nav-trigger{" thes__nav-link--current" if is_active_parent else ""}">{label}</span>'
            parent_class = "thes__nav-item thes__nav-item--parent" + (" thes__nav-item--active" if is_active_parent else "")
            html.append(
                f'<li class="{parent_class}">'
                f'<span class="thes__nav-item-row">{trigger}'
                f'<button type="button" class="thes__nav-caret" aria-label="Show {label} submenu" '
                f'aria-expanded="false" aria-controls="{submenu_id}"></button>'
                f'</span>'
                f'<ul class="thes__nav-submenu" id="{submenu_id}">{child_html}</ul></li>'
            )
        else:
            link_attrs = ' class="thes__nav-link--current" aria-current="page"' if is_current else ""
            item_class = "thes__nav-item" + (" thes__nav-item--active" if is_current else "")
            html.append(f'<li class="{item_class}"><a href="{href}"{link_attrs}>{label}</a></li>')
    return "\n".join(html)


def build_header(context, current_page_url=None):
    nav_items = render_nav_items(load_site().get("nav", []), context, current_page_url)
    return render((TEMPLATES / "header.html.tmpl").read_text(), {**context, "NAV_ITEMS": nav_items})


def render_breadcrumb(nav_items, current_page_url, context):
    """A small "Parent / Current Page" trail placed above a subpage's own
    <h1> (see the {{BREADCRUMB}} marker in whichever page templates use
    it) — the quieter, always-visible complement to render_nav_items'
    "you are here" nav highlighting: a visitor on, say, the Become a
    Sponsor page can click straight back to Ways to Give without opening
    the nav menu at all, which matters most on mobile where the nav
    starts collapsed behind the hamburger. Computed from the same
    config/site.json `nav` list current_page_url is checked against, so
    a page keeps or loses its breadcrumb automatically if it's ever
    added to or removed from a dropdown — no template edit needed
    there. "" for a top-level page (nothing to trail back to), or for a
    dropdown child whose parent has no page_url of its own to link to."""
    if not current_page_url:
        return ""
    for item in nav_items:
        for child in item.get("children") or []:
            if child.get("page_url") == current_page_url:
                parent_url_key = item.get("page_url")
                if not parent_url_key:
                    return ""
                parent_href = context[f"page_urls.{parent_url_key}"]
                return (
                    '<nav class="thes__breadcrumb" aria-label="Breadcrumb">'
                    f'<a href="{parent_href}">{item["label"]}</a>'
                    '<span aria-hidden="true"> / </span>'
                    f'<span>{child["label"]}</span>'
                    "</nav>"
                )
    return ""


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


def flyer_alt(name):
    """Alt text for a flyer thumbnail. Never alt="": Bing Webmaster
    Tools' SEO audit reports an empty alt as missing, and a flyer is
    real content (the details), not decoration."""
    return html.escape(f"Flyer: {name}") if name else "Flyer"


def render_event_attachments(attachments, event_title=""):
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
                f'<img src="{thumb_url}" alt="{flyer_alt(event_title)}" width="160" loading="lazy">'
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
        "ATTACHMENTS": render_event_attachments(event.get("attachments", []), event.get("title", "")),
        "DESCRIPTION_BLOCK": render_event_description(event.get("description")),
        "SIGNUP_BUTTON": render_event_signup(event.get("signup_href")),
        "MEET_BUTTON": render_event_meet(event.get("meet_href")),
    }


# Longest announcement text that still fits the banner's fixed two-line
# height on a small (360px) phone — measured against the real Lato font
# metrics and the banner's icon/arrow/close-button widths, not guessed.
# A third line makes the whole bar grow, and jump in height as it
# rotates between messages. Banner-graphic slides (flyer_filename) are
# exempt — their text is only the image's alt text.
ANNOUNCEMENT_MAX_CHARS = 60

ANNOUNCE_ICON_SVG = (
    '<svg class="thes__announce-icon" width="16" height="16" viewBox="0 0 24 24" '
    'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true"><path d="M11 5 6 9H2v6h4l5 4V5z"/>'
    '<path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M19 5a10 10 0 0 1 0 14"/></svg>'
)


def build_announcement_banner(announcements, context):
    """A thin, dismissible, auto-rotating announcements strip shown right
    under the header on every page — same empty-means-no-section pattern
    as sponsors/flyers/every other optional content type on this site:
    an empty config/announcements.json means this renders nothing at
    all, not an empty bar. Each announcement links somewhere relevant —
    either an internal page via `page_url` (resolved the same
    depth-aware way every other internal link on this site is, so it
    works correctly regardless of how deep the current page sits) or a
    plain external `href` — clicking anywhere on the slide navigates
    there. This is *"manage dynamically"* the same way every other
    config-only content type on this site is: editing
    config/announcements.json (see .claude/skills/add-announcement/),
    not a live/authenticated admin panel — there's no backend here to
    host one.

    More than one announcement crossfades on an interval via the
    <script> in announcement-banner.html.tmpl; a single one just sits
    still, no rotation needed. The crossfade is a sequential fade-out-
    swap-fade-in (opacity only, one slide visible at a time via
    display:none/flex) rather than the position:absolute stacking
    technique the calendar/welcome-video embeds use — deliberately, to
    avoid introducing a 5th position:absolute use beyond the ones
    "Hard-won constraints" in CLAUDE.md already vetted.

    Dismissal is remembered in the visitor's own localStorage, keyed by
    a hash of the *current* announcement set's content — so dismissing
    today's message doesn't hide a different one the PTA adds tomorrow;
    changing the config content changes the hash, which un-dismisses the
    banner for every visitor automatically without needing to touch any
    per-visitor state.

    An announcement can optionally carry `icon_filename` — a small image
    (a logo, a category icon) served from assets/images/ like every
    other image on this site, shown before the text. Every text slide
    always shows *some* icon — ANNOUNCE_ICON_SVG (a plain inline speaker
    glyph, same stroke-icon style already used in the Home page's
    quick-action cards) when no `icon_filename` is set — so the banner
    reads as a designed "badge + message + arrow" unit rather than a
    bare sentence, the single biggest visual difference between a slick
    announcement bar and a flat one per real-world examples (Elfsight/
    Popupsmart/UserGuiding). A trailing arrow (&rarr;, the same "this is
    clickable, here's where" convention already used on every card/
    button link across the rest of this site) closes out each slide for
    the same reason. No emoji anywhere in generated markup — deliberate,
    the PTA wants this professional, not casual.

    An announcement can carry a banner graphic instead of the icon+text
    treatment — either `flyer_filename` (a real flyer image, in
    assets/flyers/announcements/ like every other flyer type on this
    site, for a flyer the PTA uploaded here directly) or `flyer_href` (a
    Drive share link — for reusing a flyer that's *already* attached to
    a calendar event, via the same drive_thumbnail_url() mechanism
    events/afterschool-programs/fundraisers already use for their own
    flyer previews, so a calendar-linked announcement never needs a
    second copy of an image that's already sitting on that event).
    Either way, that entire slide becomes a full-width clickable banner
    graphic (just the image, no icon/text/arrow chrome), with a fixed
    height matching the text slides' own min-height (see
    .thes__announce-banner-img in tokens.html.tmpl) specifically so a
    banner-graphic slide and a text slide crossfade at the same height
    — same "no visible jump" requirement as everywhere else in this
    banner, just solved once more for a second slide shape.

    An announcement can carry `expires` (an ISO date, "YYYY-MM-DD") —
    once today is past that date, it's silently dropped from the
    rendered banner on the next rebuild (hourly via sync-events.yml, so
    within about an hour of actually expiring even with no human
    action), same as every other date-driven filter on this site (the
    Events page's own lookahead window works the same way). For an
    announcement linked to a real calendar event, `expires` is computed
    *once*, when the announcement is added — event date + 1 day, read
    from that event's own `date` field in config/events.json (see
    .claude/skills/add-announcement/) — rather than re-resolved live on
    every build: config/events.json is a *rolling* window of only the
    next several upcoming events, so by the time an event's expiry date
    actually arrives the event itself may have already scrolled out of
    that file, and a live lookup would fail at exactly the moment it's
    needed. Baking the literal date in at add-time sidesteps that
    entirely — same reasoning as why `flyer_href` copies the event's
    attachment URL in rather than trying to re-derive it by title match
    on every build."""
    if not announcements:
        return ""

    today = site_today(load_json("site.json"))
    announcements = [a for a in announcements if not is_expired(a.get("expires"), today)]
    if not announcements:
        return ""

    def resolve_href(a):
        if a.get("page_url"):
            # A featured event page's page_urls key only exists while that
            # page is live (see load_site), so an announcement outliving
            # its event page falls back to the Events page instead of
            # crashing the whole build with a KeyError.
            return context.get(f"page_urls.{a['page_url']}", context["page_urls.events"])
        return a.get("href", "#")

    def render_icon(a):
        filename = a.get("icon_filename")
        if filename:
            return f'<img class="thes__announce-icon" src="{context["IMAGES_BASE_URL"]}/{filename}" alt="">'
        return ANNOUNCE_ICON_SVG

    def resolve_banner_image(a):
        filename = a.get("flyer_filename")
        if filename:
            return f'{context["FLYER_BASE_URL"]}/announcements/{filename}'
        drive_href = a.get("flyer_href")
        if drive_href:
            return drive_thumbnail_url(drive_href) or drive_href
        return None

    def render_slide(a, i):
        active_style = ' style="display:flex;opacity:1;" ' if i == 0 else " "
        href = resolve_href(a)
        banner_image = resolve_banner_image(a)
        if banner_image:
            return (
                f'<a class="thes__announce-slide thes__announce-slide--banner"{active_style}href="{href}">'
                f'<img class="thes__announce-banner-img" src="{banner_image}" alt="{a.get("text", "")}"></a>'
            )
        return (
            f'<a class="thes__announce-slide"{active_style}href="{href}">'
            f'{render_icon(a)}<span class="thes__announce-text">{a["text"]}</span>'
            f'<span class="thes__announce-arrow" aria-hidden="true">&rarr;</span></a>'
        )

    content_hash = hashlib.md5(
        json.dumps(
            [
                [
                    a.get("text", ""),
                    a.get("page_url") or a.get("href", ""),
                    a.get("icon_filename", ""),
                    a.get("flyer_filename", ""),
                    a.get("flyer_href", ""),
                    a.get("expires", ""),
                ]
                for a in announcements
            ]
        ).encode()
    ).hexdigest()[:12]

    slides = "\n".join(render_slide(a, i) for i, a in enumerate(announcements))

    tmpl = (TEMPLATES / "announcement-banner.html.tmpl").read_text()
    return render(tmpl, {**context, "ANNOUNCEMENT_SLIDES": slides, "ANNOUNCEMENT_HASH": content_hash})


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


EVENTS_PAGE_MAX = 8


def build_events_page_section(events, context):
    """Whole quick-scan highlights section on the Events page. Unlike the
    Home page teaser (which just disappears when there are no events —
    it's a preview, not the main feature), this section always renders:
    with zero synced events it shows a short "nothing posted yet" message
    instead of vanishing, since this list is the site's main date-sorted
    view of what's coming up and a visitor expects to see *something*
    here. The live calendar embed further down the page renders either
    way, regardless of this section.

    Capped at EVENTS_PAGE_MAX (8) events — config/events.json is already
    date-ascending (see scripts/sync_calendar_events.py), so this is
    simply the next 8 chronologically. No "view more" link is needed for
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


# ---- Opt-in event pages (config/event-pages.json) ----
#
# Most events only ever live on the calendar (and so in the rolling
# config/events.json highlights list). An event the PTA specifically
# wants people to find from a Google search — the Holiday Market, say —
# gets its own page at pages/events/<slug>.html instead, plus schema.org
# Event structured data so Google can show it as an event (date, place)
# in results. Opt-in on purpose: not every calendar entry is meant to be
# promoted publicly, so nothing here is derived from the calendar feed.

EVENT_PAGES_DIR = "events"


def event_page_name(event):
    return f"{EVENT_PAGES_DIR}/{event['slug']}.html"


def format_event_time(t):
    hour = t.hour % 12 or 12
    suffix = "AM" if t.hour < 12 else "PM"
    return f"{hour}:{t.minute:02d} {suffix}"


def format_event_when(event):
    start = dt.datetime.fromisoformat(event["start"])
    end = dt.datetime.fromisoformat(event["end"]) if event.get("end") else None
    day = f"{start:%A, %B} {start.day}, {start.year}"
    if end and end.date() == start.date():
        return f"{day} · {format_event_time(start)} – {format_event_time(end)}"
    if end:
        return f"{day}, {format_event_time(start)} – {end:%A, %B} {end.day}, {format_event_time(end)}"
    return f"{day} · {format_event_time(start)}"


def event_location_address(event, site):
    return event.get("address") or f'{site.get("address_line1", "")}, {site.get("address_line2", "")}'


def build_postal_address(line1, line2):
    """schema.org PostalAddress from a street line + a free-text
    "City, ST 12345" line — see build_organization_jsonld for why it's
    parsed best-effort rather than stored pre-split in config."""
    address = {"@type": "PostalAddress", "streetAddress": line1}
    m = re.match(r"^\s*(.+?),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)\s*$", line2)
    if m:
        address["addressLocality"] = m.group(1)
        address["addressRegion"] = m.group(2)
        address["postalCode"] = m.group(3)
    elif line2:
        address["addressLocality"] = line2
    address["addressCountry"] = "US"
    return address


def site_city(site):
    """The city from address_line2 ("Columbia, MD 21045" -> "Columbia")."""
    return site.get("address_line2", "").split(",")[0].strip()


def site_location_short(site):
    """"Columbia, MD" — appended to every page's <title> so each page
    (and every featured event page) carries the town people search by."""
    m = re.match(r"^\s*(.+?),\s*([A-Z]{2})\b", site.get("address_line2", ""))
    return f"{m.group(1)}, {m.group(2)}" if m else site_city(site)


def site_address_line2_long(site):
    """address_line2 with the state spelled out ("Columbia, Maryland
    21045") for the footer — people search the full state name."""
    line2 = site.get("address_line2", "")
    state_name = site.get("state_name")
    if not state_name:
        return line2
    return re.sub(r",\s*[A-Z]{2}(\s+\d{5}(?:-\d{4})?)?\s*$", lambda m: f", {state_name}{m.group(1) or ''}", line2)


def build_event_jsonld(event, site):
    """schema.org Event structured data for one opt-in event page — what
    Google's event search results read (name, date, place, image), so
    the event can show up *as an event* rather than just a blue link.
    Dates carry a real UTC offset computed from the calendar's timezone
    (EST vs EDT) rather than a hardcoded one."""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(site["calendar"]["timezone"])
    domain = site["custom_domain"]

    def iso(value):
        return dt.datetime.fromisoformat(value).replace(tzinfo=tz).isoformat()

    line1 = event.get("address_line1") or site.get("address_line1", "")
    line2 = event.get("address_line2") or site.get("address_line2", "")
    data = {
        "@context": "https://schema.org",
        "@type": "Event",
        "name": event["title"],
        "description": event["summary"],
        "startDate": iso(event["start"]),
        "eventStatus": "https://schema.org/EventScheduled",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "location": {
            "@type": "Place",
            "name": event.get("location_name") or site.get("school_name", ""),
            "address": build_postal_address(line1, line2),
        },
        "organizer": {
            "@type": "Organization",
            "name": site.get("org_name", ""),
            "url": f"https://{domain}/",
        },
        "url": f"https://{domain}/{event_page_name(event)}",
    }
    if site.get("county") and not event.get("address_line2"):
        # Only for on-site events at the school's own address — an
        # off-site event's county isn't known here.
        data["location"]["containedInPlace"] = {
            "@type": "AdministrativeArea",
            "name": f'{site["county"]}, {site.get("state_name", "")}'.rstrip(", "),
        }
    if event.get("end"):
        data["endDate"] = iso(event["end"])
    if event.get("flyer_filename"):
        data["image"] = [f"https://{domain}/flyers/{event['flyer_filename']}"]
    return f'<script type="application/ld+json">{json.dumps(data)}</script>\n'


def google_calendar_add_url(event, site):
    """A one-click "add this event to my Google Calendar" link — just
    this one event, unlike the Events page's subscribe-to-everything
    link."""
    def stamp(value):
        return dt.datetime.fromisoformat(value).strftime("%Y%m%dT%H%M%S")

    end = event.get("end") or event["start"]
    params = {
        "action": "TEMPLATE",
        "text": event["title"],
        "dates": f"{stamp(event['start'])}/{stamp(end)}",
        "ctz": site["calendar"]["timezone"],
        "details": f'{event["summary"]}\n\nhttps://{site["custom_domain"]}/{event_page_name(event)}',
        "location": f'{event.get("location_name", "")}, {event_location_address(event, site)}',
    }
    return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(params)


CHECK_ICON = (
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2"><path d="M20 6 9 17l-5-5"/></svg>'
)


def render_event_page(event, site, context):
    """One opt-in event page's body — the same shared template for every
    entry in config/event-pages.json, filled in from that entry."""
    esc = html.escape
    email = event.get("contact_email") or site.get("email", "")
    contact = f'<a href="mailto:{esc(email)}">{esc(email)}</a>'
    if event.get("contact_name"):
        contact = f'{esc(event["contact_name"])} · {contact}'

    actions = []
    if event.get("register_href"):
        actions.append(
            f'<a class="thes__btn thes__btn--teal" href="{esc(event["register_href"])}" '
            'target="_blank" rel="noopener">Register as a Vendor &rarr;</a>'
        )
    actions.append(
        f'<a class="thes__btn thes__btn--navy" href="{esc(google_calendar_add_url(event, site))}" '
        'target="_blank" rel="noopener">Add to Google Calendar</a>'
    )
    if event.get("flyer_filename"):
        actions.append(
            f'<a class="thes__btn thes__btn--outline" href="{context["FLYER_BASE_URL"]}/{esc(event["flyer_filename"])}" '
            'target="_blank" rel="noopener">View Flyer</a>'
        )

    about = "\n".join(
        f'        <p style="color:var(--text-muted); margin:0 0 14px;">{esc(p)}</p>' for p in event.get("about", [])
    )

    section_cards = []
    for section in event.get("sections", []):
        items = "\n".join(
            f"            <li>{CHECK_ICON}<span>{esc(item)}</span></li>" for item in section.get("items", [])
        )
        extra = ""
        if section.get("note"):
            extra = f'\n        <p style="margin:0; color:var(--text-muted); font-size:0.9rem;">{esc(section["note"])}</p>'
        if section.get("button_href"):
            extra += (
                f'\n        <div><a class="thes__btn thes__btn--teal" href="{esc(section["button_href"])}" '
                f'target="_blank" rel="noopener">{esc(section.get("button_label") or "Learn More")} &rarr;</a></div>'
            )
        section_cards.append(
            '      <div class="thes__info-card">\n'
            f'        <h2 style="font-size:clamp(1.15rem,2.4vw,1.4rem);">{esc(section["heading"])}</h2>\n'
            f'        <ul class="thes__checklist">\n{items}\n        </ul>{extra}\n'
            "      </div>"
        )

    flyer = ""
    if event.get("flyer_filename"):
        flyer_url = f'{context["FLYER_BASE_URL"]}/{esc(event["flyer_filename"])}'
        flyer = (
            '  <section class="thes__section">\n'
            '    <div class="thes__wrap">\n'
            '      <div class="thes__section-head"><h2>Event Flyer</h2></div>\n'
            f'      <a href="{flyer_url}" target="_blank" rel="noopener">'
            f'<img src="{flyer_url}" alt="{esc(event.get("flyer_alt") or event["title"] + " flyer")}" '
            'loading="lazy" style="display:block; width:100%; max-width:900px; height:auto; margin:0 auto; '
            'border-radius:14px; border:1px solid var(--border);"></a>\n'
            "    </div>\n"
            "  </section>"
        )

    location = f'{esc(event.get("location_name") or site.get("school_name", ""))}<br>{esc(event_location_address(event, site))}'
    if site.get("county") and not event.get("address_line2"):
        location += f' · {esc(site["county"])}'
    tmpl = (TEMPLATES / "event-page.html.tmpl").read_text()
    return render(tmpl, {
        **context,
        "PAGE_TITLE": colorize_title_words(esc(event["title"])),
        "EVENT_TITLE": esc(event["title"]),
        "EVENT_EYEBROW": esc(event.get("eyebrow") or "Featured Event"),
        "EVENT_TAGLINE": esc(event.get("tagline", "")),
        "EVENT_WHEN": esc(format_event_when(event)),
        "EVENT_LOCATION": location,
        "EVENT_CONTACT": contact,
        "EVENT_ACTIONS": "\n          ".join(actions),
        "EVENT_ABOUT": about,
        "EVENT_SECTIONS": "\n".join(section_cards),
        "EVENT_FLYER": flyer,
    })


def build_event_pages_section(event_pages, context):
    """"Featured Events" cards on the Events page, one per active
    (unexpired) featured event page, soonest first. "" (no section) when
    there are none, same empty-means-no-section pattern as
    sponsors/flyers."""
    upcoming = sorted(event_pages, key=lambda e: e["start"])
    if not upcoming:
        return ""
    prefix = context["page_urls.events"].removesuffix("events.html")
    cards = "\n".join(
        '        <div class="thes__card thes__card--teal">\n'
        f'          <h3>{html.escape(e["title"])}</h3>\n'
        f'          <p><strong>{html.escape(format_event_when(e))}</strong></p>\n'
        f'          <p>{html.escape(e.get("tagline", ""))}</p>\n'
        f'          <a href="{prefix}{event_page_name(e)}">Event Details &rarr;</a>\n'
        "        </div>"
        for e in upcoming
    )
    return (
        '<section class="thes__section">\n'
        '  <div class="thes__wrap">\n'
        '    <div class="thes__section-head">\n'
        '      <span class="thes__eyebrow">Don\'t Miss</span>\n'
        "      <h2>Featured Events</h2>\n"
        "    </div>\n"
        '    <div class="thes__grid">\n'
        f"{cards}\n"
        "    </div>\n"
        "  </div>\n"
        "</section>"
    )


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
            f'<img src="{flyer_url}" alt="{flyer_alt(program.get("name"))}" width="160" loading="lazy">'
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


def render_fundraiser_card(campaign, context, status_html=""):
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
    parts = []
    # "direct" cards skip the category badge — they all sit under a
    # "Give Directly" section heading already, so a badge on every card
    # in that section would just repeat what the heading already said.
    if category != "direct":
        parts.append(f'<span class="thes__badge thes__badge--fund-{category}">{FUNDRAISER_CATEGORY_LABELS[category]}</span>')
    parts.append(status_html)
    parts.append(f'<h3>{campaign["name"]}</h3>')
    parts.append(f'<p>{campaign["description"]}</p>')

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
        code_label = campaign.get("code_label") or "Enrollment code"
        parts.append(f'<p class="thes__fund-code">{code_label}: <strong>{campaign["enrollment_code"]}</strong></p>')

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
            f'<img src="{flyer_url}" alt="{flyer_alt(campaign.get("name"))}" width="160" loading="lazy">'
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


def fundraiser_status_html(occurrence):
    """"Happening now · through Oct 16" / "Coming up · Nov 3, 5–8 PM" —
    the line that makes a Current Fundraisers card read as time-bound."""
    if occurrence["status"] == "now":
        end = occurrence["dates"].split(" – ")[-1]
        if " " not in end:  # "Oct 3 – 10" -> "Oct 10"
            end = f'{occurrence["dates"].split(" ")[0]} {end}'
        label, when = "Happening now", (f"through {end}" if occurrence["end_date"] != occurrence["start_date"] else "today")
    else:
        label = "Coming up"
        when = occurrence["dates"] if occurrence["when"] == "All Day" else f'{occurrence["dates"]}, {occurrence["when"]}'
    return f'<p class="thes__fund-howto"><strong>{label}</strong> · {html.escape(when)}</p>'


def render_calendar_fundraiser_card(occurrence, context):
    """A Current Fundraisers card built straight from a calendar event —
    for a fundraiser nobody has written a richer config entry for (see
    `calendar_match` in config/fundraisers.json)."""
    parts = [
        '<span class="thes__badge thes__badge--fund-seasonal">Fundraiser</span>',
        fundraiser_status_html(occurrence),
        f'<h3>{html.escape(occurrence["title"])}</h3>',
    ]
    if occurrence.get("description"):
        parts.append(f'<p>{occurrence["description"]}</p>')
    if occurrence.get("signup_href"):
        parts.append(f'<div class="thes__fund-actions">{render_event_signup(occurrence["signup_href"])}</div>')
    parts.append(render_event_attachments(occurrence.get("attachments", []), occurrence["title"]))
    return f'<div class="thes__fund-card">{"".join(parts)}</div>'


def build_current_fundraisers_section(occurrences, linked_campaigns, context):
    """"Current Fundraisers" — every calendar event with "fundraiser" in
    its title that's running now or starts within the next ~60 days
    (config/fundraiser-occurrences.json, from
    scripts/sync_calendar_events.py), soonest first. A config entry
    whose `calendar_match` appears in an occurrence's title (e.g. "Joe
    Corbi" -> the Joe Corbi's and Believe Kids cards, with their
    ShopFund links and seller code) replaces that occurrence's plain
    calendar card, and only ever shows here, while the calendar says
    it's on — so a yearly campaign's entry can stay in config between
    seasons without showing up out of season. "" when nothing's current."""
    cards = []
    for occ in occurrences:
        matched = [c for c in linked_campaigns if c["calendar_match"].lower() in occ["title"].lower()]
        if matched:
            cards += [render_fundraiser_card(c, context, fundraiser_status_html(occ)) for c in matched]
        else:
            cards.append(render_calendar_fundraiser_card(occ, context))
    if not cards:
        return ""
    body = "\n".join(indent(c, 6) for c in cards)
    return (
        '<section class="thes__section">\n'
        '  <div class="thes__wrap">\n'
        '    <div class="thes__section-head">\n'
        '      <span class="thes__eyebrow">Happening Now</span>\n'
        "      <h2>Current Fundraisers</h2>\n"
        "      <p>Running now or coming up soon — straight from the PTA calendar.</p>\n"
        "    </div>\n"
        '    <div class="thes__fund-grid">\n'
        f"{body}\n"
        "    </div>\n"
        "  </div>\n"
        "</section>"
    )


def build_fundraising_section(campaigns, context, occurrences=()):
    """Whole Fundraising page body: campaigns grouped into a couple of
    visually-balanced sections (see FUNDRAISER_GROUPS) plus a closing
    full-width "Give Directly" band — a single-card grid for a one-entry
    category would read as sparse, so it gets the same treatment as
    committees.html's "Not Sure Where to Help?" closer instead. Same
    empty-means-a-placeholder-message pattern as the other always-in-nav
    pages (afterschool programs, events)."""
    linked = [c for c in campaigns if c.get("calendar_match")]
    campaigns = [c for c in campaigns if not c.get("calendar_match")]
    current = build_current_fundraisers_section(occurrences, linked, context)
    if not campaigns and not current:
        return (TEMPLATES / "fundraising-empty.html.tmpl").read_text()

    by_category = {}
    for c in campaigns:
        by_category.setdefault(c["category"], []).append(c)
    direct = by_category.pop("direct", [])

    sections = [current] if current else []
    tint = bool(current)

    # "Give Directly" leads the page — the most immediate, no-research-
    # needed way to help, ahead of the other campaigns that each take a
    # minute to read and act on. Every "direct" entry (a cash donation,
    # an in-kind item wish list, whatever else gets added later) is a
    # card in this one section — no special single-CTA band for the
    # first one, since that previously left the section reading as
    # "Give Directly" the heading right above a card *also* titled "Give
    # Directly" right above a second card badged "Direct Giving": three
    # ways of saying the same thing. One heading, N cards, done.
    if direct:
        cards = "\n".join(indent(render_fundraiser_card(c, context), 6) for c in direct)
        section_class = "thes__section thes__section--tint" if tint else "thes__section"
        sections.append(
            f'<section class="{section_class}">\n'
            '  <div class="thes__wrap">\n'
            '    <div class="thes__section-head">\n'
            "      <h2>Give Directly</h2>\n"
            "      <p>No purchase required — every one of these goes straight to THES students.</p>\n"
            "    </div>\n"
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


def render_sponsorship_tier_card(tier):
    """One sponsorship-level card on the Sponsors page — same
    `.thes__card` shape every other simple card grid on this site uses
    (afterschool programs, family support resources), with a colored
    price badge (`color` in config picks which `.thes__badge--tier-*`
    modifier applies — see tokens.html.tmpl) so the four levels read as
    a clear ladder at a glance, same as the flyer these tiers were
    transcribed from. `checkout_href`, when set, is that tier's specific
    Givebacks shop item — a direct "buy this exact level right now" path
    that doesn't require going through the interest form first, for a
    business that already knows which level it wants."""
    benefits = "".join(f"<li>{b}</li>" for b in tier.get("benefits", []))
    checkout_href = tier.get("checkout_href")
    checkout_button = ""
    if checkout_href:
        checkout_button = (
            f'<a class="thes__btn thes__btn--teal" href="{checkout_href}" target="_blank" rel="noopener">'
            "Click to Sponsor at This Level &rarr;</a>"
        )
    return (
        f'<div class="thes__card thes__card--{tier["color"]}">'
        f'<span class="thes__badge thes__badge--tier-{tier["color"]}">{tier["price"]}</span>'
        f'<h3>{tier["name"]}</h3>'
        f'<ul class="thes__checklist-plain">{benefits}</ul>'
        f"{checkout_button}"
        "</div>"
    )


def render_sponsor_cta(info):
    """The closing "have questions?" block on the Become a Sponsor page —
    an embedded Google Form (sponsorship level + a message, so a
    business with a question or a custom request can just submit right
    there) once `interest_form_embed_src` is set in config/sponsorship.json,
    or a plain mailto CTA until then. Deliberately framed as the
    questions/custom-request path, not the primary way to sponsor — each
    tier card above now has its own "Buy Now" button straight to that
    level's Givebacks shop item (render_sponsorship_tier_card's
    checkout_href) for a business that already knows which level it
    wants, so this section exists for everyone else. Same empty-means-
    simpler-fallback shape as everywhere else on this site rather than a
    broken/missing embed: this repo has no Google Forms API access to
    create the form itself, so a human sets it up (Google Forms has no
    native way to email more than the one form owner on a new response —
    a shared PTA inbox as the owner, or a Sheet + Apps Script trigger,
    are the two ways to actually notify more than one person) and pastes
    the finished embed link into config once it's ready.
    `interest_form_embed_height` is a fixed pixel height (not the
    aspect-ratio-box technique the calendar/welcome-video embeds use,
    since a form's natural height doesn't correspond to any fixed ratio
    the way a calendar or video does) — Google's own "Send > embed" panel
    shows the right value for the specific form, so it's config, not
    guessed."""
    embed_src = info.get("interest_form_embed_src")
    embed_height = info.get("interest_form_embed_height", 1200)
    contact_name = info.get("contact_name", "")
    contact_role = info.get("contact_role", "")
    contact_email = info.get("contact_email", "")
    if embed_src:
        return (
            '<div class="thes__section-head">'
            "<h2>Have Questions?</h2>"
            "<p>Ready to sponsor a specific level? Use its &ldquo;Buy Now&rdquo; button above. "
            "Have a question, a custom request, or want to sponsor a different way? Fill out the form below and we&rsquo;ll follow up.</p>"
            "</div>"
            '<div class="thes__form-embed">'
            f'<iframe src="{embed_src}" width="100%" height="{embed_height}" frameborder="0" marginheight="0" marginwidth="0">Loading&hellip;</iframe>'
            "</div>"
            f'<p class="thes__form-embed-fallback">Prefer email? Contact {contact_name}, {contact_role}, '
            f'at <a href="mailto:{contact_email}">{contact_email}</a>.</p>'
        )
    return (
        '<div class="thes__join">'
        "<h2>How to Become a Sponsor</h2>"
        f"<p>Ready to sponsor? Contact {contact_name}, {contact_role}, to get started.</p>"
        f'<a class="thes__btn thes__btn--navy" href="mailto:{contact_email}">Email {contact_email} &rarr;</a>'
        "</div>"
    )


def build_sponsorship_section(info, context):
    """Whole Sponsors page's tier/benefit content, sourced from
    config/sponsorship.json — deliberately a *separate* config file from
    config/sponsors.json (the list of businesses that have actually
    joined, shown just below this via the existing {{SPONSORS_SECTION}}
    marker): one is "how sponsorship works," the other is "who's already
    sponsoring," and they change independently. "" if the config is
    missing/empty (shouldn't normally happen — unlike sponsors/flyers,
    this isn't meant to ever go to zero — but a missing file should never
    hard-crash the whole build)."""
    if not info:
        return ""
    why_items = "".join(f"<li>{w}</li>" for w in info.get("why_sponsor", []))
    tier_cards = "\n".join(indent(render_sponsorship_tier_card(t), 6) for t in info.get("tiers", []))
    perks = "".join(f"<li>{p}</li>" for p in info.get("all_sponsors_perks", []))
    tmpl = (TEMPLATES / "sponsorship-section.html.tmpl").read_text()
    return render(tmpl, {
        **context,
        "SPONSORSHIP_INTRO": info.get("intro", ""),
        "WHY_SPONSOR_ITEMS": why_items,
        "TIER_CARDS": tier_cards,
        "ALL_SPONSORS_PERKS": perks,
        "SPONSOR_CTA_BLOCK": indent(render_sponsor_cta(info), 4),
    })


def build_sponsors_page_section(sponsors, context):
    """The "Our Sponsors" section on the Sponsors page itself — unlike
    build_optional_section's usual empty-means-no-section pattern (still
    used for this exact same config file on the Home page's rotating
    teaser), this section always renders here: a prospective sponsor is
    reading this page specifically to decide whether to join, so they
    need to actually see where their name/logo would land, not have the
    section silently vanish because nobody's signed up yet. Shows a
    single dashed placeholder card in that case instead."""
    card_tmpl = (TEMPLATES / "card-sponsor.html.tmpl").read_text()
    if sponsors:
        cards = "\n".join(indent(render(card_tmpl, s), 8) for s in sponsors)
    else:
        cards = indent(
            '<div class="thes__card thes__card--placeholder">'
            "<h3>Your Business Here</h3>"
            "<p>Become our next sponsor and get featured in this spot.</p>"
            "</div>",
            8,
        )
    section_tmpl = (TEMPLATES / "joined-sponsors-section.html.tmpl").read_text()
    return render(section_tmpl, {**context, "SPONSOR_CARDS": cards})


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
        f'<img src="{flyer_url}" alt="{flyer_alt(meeting.get("title"))}" width="160" loading="lazy">'
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
    address = build_postal_address(site.get("address_line1", ""), site.get("address_line2", ""))

    data = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": site.get("org_name", ""),
        "alternateName": ["THES PTA", f'{site.get("school_short_name", "")} PTA'],
        "description": (
            f'The parent-teacher association of {site.get("school_name", "")}, a '
            f'{site.get("school_district", "")} elementary school in '
            f'{site_city(site)}, {site.get("state_name", "")}.'
        ),
        "areaServed": [
            {"@type": "City", "name": f'{site_city(site)}, {site.get("state_name", "")}'},
            {"@type": "AdministrativeArea", "name": f'{site.get("county", "")}, {site.get("state_name", "")}'},
        ],
        "url": f'https://{site["custom_domain"]}/',
        "logo": f'https://{site["custom_domain"]}/images/{site["hero_image_filename"]}',
        "email": site.get("email", ""),
        "address": address,
        "sameAs": [href for href in site.get("social", {}).values() if href],
    }
    return f'<script type="application/ld+json">{json.dumps(data)}</script>\n'


def build_document_title(page_name, site, nav_labels, event_page=None):
    """The <title> — the blue link in search results, and the strongest
    single signal of what a page is about. Every page carries the town
    ("Columbia, MD"); the Home page also names the county, since that's
    the page a "Howard County PTA" search should land on. Inner pages
    lead with their own name (what a searcher — or a visitor with
    several tabs open — needs first), taken from its nav label, then
    PAGE_TITLES, then the filename."""
    org = site.get("org_name", "")
    where = site_location_short(site)
    if page_name == "index.html":
        county = f' · {site["county"]}' if site.get("county") else ""
        return html.escape(f"{org} | {where}{county}")
    if event_page:
        return html.escape(f'{event_page["title"]} · {where} | {org}')
    name = nav_labels.get(page_name) or PAGE_TITLES.get(page_name) or Path(page_name).stem.replace("-", " ").title()
    return html.escape(f"{name} | {org} · {where}")


EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Things the pattern above also matches that aren't email addresses.
NOT_EMAILS = re.compile(r"@group\.calendar\.google\.com$|\.(png|jpe?g|gif|svg|webp|css|js)$", re.I)


def is_allowed_email(address, site):
    """PTA addresses (anything with "thespta" before the @, e.g.
    president.thespta@gmail.com) are always fine; anything else has to be
    approved one by one in config/site.json's `approved_emails`."""
    local = address.split("@", 1)[0].lower()
    approved = {a.lower() for a in site.get("approved_emails", [])}
    return "thespta" in local or address.lower() in approved


def hide_unapproved_emails(text, site, page_name, pending):
    """The PTA's rule: the website never shows a personal email unless
    the PTA approved that exact address. Runs over every finished page,
    so it also catches addresses arriving indirectly — a calendar
    event's Description (synced hourly, no human in the loop), flyer
    details typed into config — not just ones added on purpose.

    An unapproved address is *hidden* — a mailto link around it is
    dropped entirely, a bare address is removed — never swapped for a
    different contact (the PTA asked for that explicitly). It's
    collected in `pending` and listed after the build, so whoever is
    working with the PTA can ask them about each one; approving means
    adding it to `approved_emails` in config/site.json."""

    def allowed(address):
        return NOT_EMAILS.search(address) or is_allowed_email(address, site)

    def note(address):
        pending.setdefault(address.lower(), (address, set()))[1].add(page_name)

    def drop_link(m):
        address = m.group(1)
        if allowed(address):
            return m.group(0)
        note(address)
        return ""

    text = re.sub(r'<a\b[^>]*href="mailto:([^"?]+)[^"]*"[^>]*>.*?</a>', drop_link, text, flags=re.S)

    def drop_bare(m):
        address = m.group(0)
        if allowed(address):
            return address
        note(address)
        return ""

    return EMAIL_PATTERN.sub(drop_bare, text)


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
    "become-a-sponsor.html": "Become a Sponsor",
    "sponsors.html": "Our Sponsors",
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
        "Columbia, Maryland — events, PTA meetings, volunteering, and fundraising "
        "for our Howard County school community."
    ),
    "about.html": (
        "Meet the Thunder Hill Elementary PTA Executive Board and learn about our "
        "mission to support students, staff, and families at THES in Columbia, "
        "Maryland (Howard County)."
    ),
    "get-involved.html": (
        "Volunteer opportunities, committees, and membership for the Thunder Hill "
        "Elementary PTA in Columbia, MD — get involved at our Howard County school."
    ),
    "events.html": (
        "Upcoming Thunder Hill Elementary PTA events in Columbia, MD — family "
        "nights, fundraisers, and PTA meetings for our Howard County school "
        "community."
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
    "become-a-sponsor.html": (
        "Become a Thunder Hill Elementary PTA sponsor — sponsorship levels, "
        "benefits, and how local businesses can support our students."
    ),
    "sponsors.html": (
        "The local businesses sponsoring Thunder Hill Elementary PTA — thank "
        "you for supporting our students, teachers, and families."
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
    announcements = load_json("announcements.json", default=[])
    for a in announcements:
        if not a.get("flyer_filename") and len(a.get("text", "")) > ANNOUNCEMENT_MAX_CHARS:
            print(f'  ! announcement is {len(a["text"])} characters (max {ANNOUNCEMENT_MAX_CHARS}) — '
                  f'it will wrap to a third line on phones and grow the banner: "{a["text"]}"')
    site = load_site()
    committees_section = build_committees_section(
        load_json("committees.json", default=[]), site["volunteerForm"]
    )
    welcome_video_section = build_welcome_video_section(site)
    organization_jsonld = build_organization_jsonld(site)
    event_pages = load_active_event_pages(site)
    for e in event_pages:
        if site_city(site) and site_city(site).lower() not in e.get("summary", "").lower():
            print(f'  ! event page "{e["slug"]}": summary doesn\'t mention {site_city(site)} — '
                  "it's the search-result snippet; name the town so local searches match")

    # Inverse of page_urls (e.g. "get-involved/committees" -> "committees")
    # so the nav can mark "you are here" — see render_nav_items — from
    # nothing but the page filename already being built, with no need for
    # every page template to separately declare which nav item is its own.
    page_url_keys_by_name = {v: k for k, v in site.get("page_urls", {}).items()}
    nav_labels = {
        f'{site["page_urls"][item["page_url"]]}.html': item["label"]
        for top in site.get("nav", [])
        for item in [top] + (top.get("children") or [])
        if item.get("page_url") in site.get("page_urls", {})
    }

    page_templates = sorted((TEMPLATES / "pages").rglob("*.html.tmpl"))
    if not page_templates:
        raise SystemExit("No page templates found in src/templates/pages/")

    # Every page is (page_name, template path, opt-in event or None):
    # the hand-written page templates, plus one generated page per entry
    # in config/event-pages.json, all sharing event-page.html.tmpl. Both
    # go through the exact same document shell/header/sitemap handling
    # below — an event page is a real page, not a special case of one.
    page_jobs = [
        (str(p.relative_to(TEMPLATES / "pages")).removesuffix(".tmpl"), p, None) for p in page_templates
    ]
    page_jobs += [(event_page_name(e), TEMPLATES / "event-page.html.tmpl", e) for e in event_pages]

    PAGES_OUT.mkdir(exist_ok=True)
    # pages/events/ holds nothing but generated featured-event pages, so
    # it's cleared on every build — otherwise an expired/archived event's
    # old HTML would linger in pages/ and keep getting deployed (both
    # workflows copy pages/ wholesale into the site).
    for stale in (PAGES_OUT / EVENT_PAGES_DIR).glob("*.html"):
        stale.unlink()
    context_by_depth = {}
    built_page_names = []
    pending_emails = {}

    for page_name, tmpl_path, event_page in page_jobs:
        depth = page_name.count("/")

        # Everything that depends on page_urls.*/HERO_IMAGE_URL/etc has to
        # be rebuilt per depth — a page one directory down needs "../"
        # prefixes a top-level page doesn't. Cheap to just rebuild (this
        # site has a handful of pages total) and memoizing per depth
        # avoids redoing it once per page at the same depth.
        if depth not in context_by_depth:
            context_by_depth[depth] = build_context(depth)
        context = context_by_depth[depth]
        tokens = build_tokens(context)
        current_page_url = page_url_keys_by_name.get(page_name.removesuffix(".html"))
        header = build_header(context, current_page_url)
        breadcrumb = render_breadcrumb(site.get("nav", []), current_page_url, context)
        announcement_banner = build_announcement_banner(announcements, context)
        footer = build_footer(context)
        home_events_section = build_home_events_section(events, context)
        events_page_section = build_events_page_section(events, context)
        sponsors_section = build_optional_section(
            "sponsors.json", "card-sponsor.html.tmpl", "sponsors-section.html.tmpl", "SPONSOR_CARDS", context
        )
        sponsorship_section = build_sponsorship_section(load_json("sponsorship.json", default={}), context)
        joined_sponsors_section = build_sponsors_page_section(load_json("sponsors.json", default=[]), context)
        flyers_section = build_optional_section(
            "flyers.json", "card-flyer.html.tmpl", "flyers-section.html.tmpl", "FLYER_CARDS", context
        )
        fundraising_section = build_fundraising_section(
            load_json("fundraisers.json", default=[]), context,
            load_json("fundraiser-occurrences.json", default=[]),
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
        event_pages_section = build_event_pages_section(event_pages, context)

        shared_markers = {
            "{{TOKENS}}": tokens,
            "{{BREADCRUMB}}": breadcrumb,
            "{{FOOTER}}": footer,
            "{{BOARD_CARDS}}": board_cards,
            "{{EVENTS_SECTION}}": home_events_section,
            "{{EVENTS_LIST_SECTION}}": events_page_section,
            "{{SPONSORS_SECTION}}": sponsors_section,
            "{{SPONSORSHIP_SECTION}}": sponsorship_section,
            "{{JOINED_SPONSORS_SECTION}}": joined_sponsors_section,
            "{{FLYERS_SECTION}}": flyers_section,
            "{{COMMITTEES_SECTION}}": committees_section,
            "{{WELCOME_VIDEO_SECTION}}": welcome_video_section,
            "{{AFTERSCHOOL_PROGRAMS_SECTION}}": afterschool_programs_section,
            "{{FUNDRAISING_SECTIONS}}": fundraising_section,
            "{{PTA_MEETINGS_SECTION}}": pta_meetings_section,
            "{{FAMILY_SUPPORT_RESOURCES_SECTION}}": family_support_resources_section,
            "{{HCPSS_EVENTS_SECTION}}": hcpss_events_section,
            "{{EVENT_PAGES_SECTION}}": event_pages_section,
        }

        page_context = context
        if page_name in PAGE_TITLES:
            page_context = {**context, "PAGE_TITLE": colorize_title_words(PAGE_TITLES[page_name])}
        if event_page:
            text = render_event_page(event_page, site, context)
        else:
            text = render(tmpl_path.read_text(), page_context)
        for marker, value in shared_markers.items():
            text = text.replace(marker, value)

        # Decoupled from each page template's own markup on purpose: the
        # header is inserted structurally right after `<div class="thes">`
        # opens, rather than relying on a `{{HEADER}}` marker every page
        # template has to remember to include. A real page once shipped
        # without one (copied from before this branch had a header at
        # all) because nothing enforced its presence — this makes it
        # impossible for any current or future page to omit it. The
        # announcement banner (built above, "" when config/announcements.json
        # is empty) rides along in this same structural insertion, right
        # below the header, for the same reason — every page gets it with
        # no per-template marker to remember.
        header_block = header + (f"\n{announcement_banner}" if announcement_banner else "")
        text = text.replace('<div class="thes">', f'<div class="thes">\n{header_block}', 1)

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
        page_jsonld = organization_jsonld
        if event_page:
            page_jsonld += build_event_jsonld(event_page, site)
        document_title = build_document_title(page_name, site, nav_labels, event_page)
        analytics_snippet = build_analytics_snippet(context.get("google_analytics_id", ""))
        analytics_snippet += build_umami_snippet(context.get("umami_website_id", ""))
        page_description = PAGE_DESCRIPTIONS.get(page_name, PAGE_DESCRIPTIONS["index.html"])
        if event_page:
            page_description = html.escape(event_page["summary"])
        canonical_url = f'https://{site["custom_domain"]}/{"" if page_name == "index.html" else page_name}'
        text = (
            "<!DOCTYPE html>\n"
            '<html lang="en">\n<head>\n'
            f"{analytics_snippet}"
            '<meta charset="UTF-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<meta name="description" content="{page_description}">\n'
            f'<link rel="canonical" href="{canonical_url}">\n'
            f"<title>{document_title}</title>\n"
            f"{page_jsonld}"
            f"</head>\n<body>\n{text}\n</body>\n</html>\n"
        )

        text = hide_unapproved_emails(text, site, page_name, pending_emails)
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

    for address, pages in pending_emails.values():
        print(f"  ! email {address} is NOT approved — hidden on {', '.join(sorted(pages))}. "
              "Ask the PTA; if they approve it, add it to approved_emails in config/site.json.")

    print(f"\nDone — {len(built_page_names)} pages written to /pages.")
    print("Push to main to deploy — GitHub Actions rebuilds, validates, and redeploys to GitHub Pages automatically.")


if __name__ == "__main__":
    main()
