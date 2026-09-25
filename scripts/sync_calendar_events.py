#!/usr/bin/env python3
"""
Pulls upcoming events from the PTA's Google Calendar and writes
config/events.json in the exact shape src/build.py expects — so the
"Upcoming Events" preview on the Home page and the quick-scan list on the
Events page stay in sync with the calendar automatically, with nobody
hand-editing config/events.json. A file attached to a calendar event (e.g.
a flyer PDF added via Google Drive in the Calendar UI) is picked up too —
confirmed empirically that Google's public .ics export includes ATTACH
properties, which isn't obviously true of a "basic" reduced feed — and
turned into a "Flyer" link on that event wherever it's shown. The Drive
file itself still needs "Anyone with the link" sharing for that link to
actually work for a visitor — attaching it to the event doesn't change its
Drive permissions.

Mentioning "sign up" near a URL anywhere in an event's Description
becomes a "Sign Up" button on that event too (see extract_signup_href
below) — a voluntary convention, not a real Calendar API field the way
ATTACH is, since Calendar has no dedicated "signup link" field to pull
from; tolerant of natural phrasing, not a strict required format. A
Google Meet link (https://meet.google.com/...) anywhere in the
Description becomes a "Join Google Meet" button the same way (see
extract_meet_href) — that one needs no nearby keyword since the domain
itself is unambiguous. Either URL is stripped out of the description
text shown on the site so it isn't duplicated.

Also writes config/pta-meeting-occurrences.json: every upcoming
occurrence whose title mentions "PTA" and "meeting" (see
is_pta_meeting_title), for the "Upcoming PTA Meetings" section on the
PTA Meetings page. This is a second, separate pass over the same
parsed calendar — not just a filter over config/events.json — because
events.json is deliberately capped to MAX_EVENTS (8) across ALL event
types for the Home/Events page highlights, so a PTA meeting further out
than the 8th nearest calendar-wide event would otherwise never surface
here at all even though it's genuinely coming up.

A calendar shared as "public" (see docs/SOP.md Task 5) exposes a free,
no-auth .ics feed at a fixed URL — the same feed config/site.json's
CAL_ICS_URL already points visitors to for "Download .ics". This script
fetches that feed and parses just enough iCalendar (RFC 5545) syntax to
list what's coming up: VEVENT/SUMMARY/DTSTART/DTEND/LOCATION/DESCRIPTION,
plus RRULE recurrence (FREQ=DAILY/WEEKLY/MONTHLY/YEARLY, INTERVAL, COUNT,
UNTIL, BYDAY — including the "first Tuesday of the month" ordinal form
PTA meetings commonly use) and EXDATE. No third-party calendar library —
stdlib only, consistent with the rest of this build system.

Run manually any time you want the site to catch up with calendar changes
right now:

    python3 scripts/sync_calendar_events.py

GitHub Actions also runs this automatically before every build — on a
daily schedule and on every push (see .github/workflows/deploy.yml) — so
this normally never needs a human to run it. Add/edit/delete events in
Google Calendar directly; that's the only source of truth now.

If the calendar has zero upcoming events, this writes an empty `[]` and
the "Upcoming Events" / quick-scan sections disappear from the site
entirely (same empty-list-means-no-section pattern as sponsors/flyers) —
not a bug, and not this script's problem to paper over.
"""
import datetime as dt
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"

LOOKAHEAD_DAYS = 180  # how far into the future to expand recurring events
MAX_EVENTS = 8        # how many upcoming events to keep as highlights — matches src/build.py's EVENTS_PAGE_MAX, the Events page's own display cap

# PTA meetings are roughly monthly but skip summer, so "the next 3" can sit
# further out than LOOKAHEAD_DAYS — a meeting scheduled for next May can be
# ~8 months away in September. Long enough to reliably catch a few, without
# also dragging in a stale meeting from a school year that hasn't started
# its calendar yet.
PTA_MEETING_LOOKAHEAD_DAYS = 400

MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
WEEKDAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def load_json(name):
    return json.loads((CONFIG / name).read_text())


def fetch_ics(calendar_id):
    url = f"https://calendar.google.com/calendar/ical/{urllib.parse.quote(calendar_id, safe='')}/public/basic.ics"
    with urllib.request.urlopen(url, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def unfold(text):
    """RFC 5545 line folding: a line starting with a space/tab continues the previous line."""
    lines = text.replace("\r\n", "\n").split("\n")
    out = []
    for line in lines:
        if line.startswith((" ", "\t")) and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def unescape_text(value):
    return (
        value.replace("\\n", " ").replace("\\N", " ")
        .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")
        .strip()
    )


TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text):
    """A calendar event's Description can contain literal HTML markup
    (<span>/<p>/<br> tags) if it was ever pasted from a rich-text source
    (Google Calendar's own description editor supports rich text) —
    confirmed for real on two different calendars now: HCPSS's, and (the
    bug this function was widened to also cover) the PTA's own, where a
    garden-cleanup event's multi-paragraph description broke a live
    deploy — DESCRIPTION_LIMIT's truncation cut the text off mid-tag,
    leaving an unclosed <p> that failed test/validate_build.py's tag-
    balance check. render_event_description in src/build.py inserts a
    Description unescaped into its own <p>, so any embedded markup
    (closed or not) ends up nested inside that wrapper. Stripped to
    plain text here, at the source, so every description this site
    renders is plain text regardless of which calendar or which
    person's paste it came from."""
    if not text:
        return text
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", text)).strip()


def parse_property_line(line):
    """'NAME;PARAM=X:VALUE' -> ("NAME", {"PARAM": "X"}, "VALUE")."""
    head, _, value = line.partition(":")
    parts = head.split(";")
    params = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            params[k] = v
    return parts[0], params, value


def parse_ics_datetime(value, local_tz):
    """DTSTART/DTEND/EXDATE value -> (naive local datetime, is_all_day).
    A trailing "Z" means UTC — converted to the calendar's configured
    timezone. A bare TZID-qualified or floating value is treated as
    already being in that local timezone (true for a single-timezone PTA
    calendar, which is the only case this needs to handle)."""
    value = value.strip()
    if len(value) == 8:
        return dt.datetime.strptime(value, "%Y%m%d"), True
    if value.endswith("Z"):
        aware_utc = dt.datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
        return aware_utc.astimezone(local_tz).replace(tzinfo=None), False
    return dt.datetime.strptime(value, "%Y%m%dT%H%M%S"), False


def parse_vevents(lines, local_tz):
    events = []
    cur = None
    for line in lines:
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT":
            if cur is not None and "DTSTART" in cur:
                events.append(cur)
            cur = None
        elif cur is not None and line.strip():
            name, params, value = parse_property_line(line)
            if name in ("DTSTART", "DTEND"):
                when, all_day = parse_ics_datetime(value, local_tz)
                cur[name] = when
                cur[name + "_ALLDAY"] = all_day
            elif name == "EXDATE":
                cur.setdefault("EXDATE", set())
                for v in value.split(","):
                    when, _ = parse_ics_datetime(v, local_tz)
                    cur["EXDATE"].add(when)
            elif name in ("SUMMARY", "LOCATION", "DESCRIPTION"):
                text = unescape_text(value)
                # Only DESCRIPTION gets HTML stripped — SUMMARY/LOCATION
                # are short, single-line fields with no real history of
                # rich-text paste, and stripping them defensively for a
                # problem that hasn't actually occurred there isn't
                # worth the (small) risk of mangling a legitimate "<"
                # character in, say, a location name.
                cur[name] = strip_html(text) if name == "DESCRIPTION" else text
            elif name == "RRULE":
                cur["RRULE"] = value
            elif name == "ATTACH":
                cur.setdefault("ATTACH", [])
                cur["ATTACH"].append({"title": params.get("FILENAME", "Flyer"), "href": value.strip()})
    return events


def parse_rrule(rrule):
    out = {}
    for chunk in rrule.split(";"):
        k, _, v = chunk.partition("=")
        out[k] = v
    return out


def matches_monthly_byday(d, byday):
    m = re.match(r"(-?\d*)([A-Z]{2})", byday)
    ordinal_str, weekday_code = m.groups()
    if WEEKDAYS.index(weekday_code) != d.weekday():
        return False
    if not ordinal_str:
        return True
    ordinal = int(ordinal_str)
    if ordinal > 0:
        return (d.day - 1) // 7 + 1 == ordinal
    next_month = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    last_day_of_month = (next_month - dt.timedelta(days=1)).day
    return (last_day_of_month - d.day) // 7 == (-ordinal - 1)


def advance(cur, freq, interval, byday):
    if freq == "DAILY":
        return cur + dt.timedelta(days=interval)
    if freq == "WEEKLY":
        return cur + dt.timedelta(weeks=interval)
    if freq == "MONTHLY":
        if byday:
            return cur + dt.timedelta(days=1)  # scanned day-by-day; see expand_occurrences
        month_index = cur.month - 1 + interval
        year = cur.year + month_index // 12
        month = month_index % 12 + 1
        day = min(cur.day, 28)
        return cur.replace(year=year, month=month, day=day)
    if freq == "YEARLY":
        try:
            return cur.replace(year=cur.year + interval)
        except ValueError:
            return cur.replace(year=cur.year + interval, day=28)
    return None


def expand_occurrences(event, window_start, window_end):
    """Yield each occurrence's start datetime within [window_start, window_end]."""
    start = event["DTSTART"]
    rrule = event.get("RRULE")
    if not rrule:
        if window_start <= start <= window_end:
            yield start
        return

    rule = parse_rrule(rrule)
    freq = rule.get("FREQ")
    interval = int(rule.get("INTERVAL", "1"))
    count = int(rule["COUNT"]) if "COUNT" in rule else None
    until = parse_ics_datetime(rule["UNTIL"], dt.timezone.utc)[0] if "UNTIL" in rule else None
    byday = rule.get("BYDAY") if freq == "MONTHLY" else None
    exdates = event.get("EXDATE", set())

    cur = start
    produced = 0
    for _ in range(3000):  # defensive cap — a malformed rule can't loop forever
        if cur is None or cur > window_end or (until and cur > until) or (count is not None and produced >= count):
            break
        matches = matches_monthly_byday(cur, byday) if byday else True
        if matches:
            if cur not in exdates and cur >= window_start:
                yield cur
            produced += 1
        cur = advance(cur, freq, interval, byday)


def format_time(d):
    return d.strftime("%-I:%M %p")


def format_when(start, end, all_day, location):
    if all_day:
        parts = ["All Day"]
    elif end and end != start:
        start_s, end_s = format_time(start), format_time(end)
        same_period = start_s[-2:] == end_s[-2:]
        parts = [f"{start_s[:-3] if same_period else start_s} – {end_s}"]
    else:
        parts = [format_time(start)]
    if location:
        parts.append(location)
    return " · ".join(parts)


SIGNUP_RE = re.compile(r"(?is)sign[\s-]?up\b.{0,60}?(https?://\S+)")


def extract_signup_href(description):
    """Finds a URL that follows the word "sign up" (however it's
    phrased — "Sign Up:", "sign up here!", "please sign-up at") within
    ~60 characters of it, anywhere in a calendar event's Description,
    and returns (signup_href_or_None, remaining_description). Only the
    URL itself is removed from the text (the surrounding "...sign up
    here!" sentence is left in place — it reads fine right above the
    button this produces, and isn't a duplicate of anything).

    Deliberately tolerant of natural phrasing rather than requiring an
    exact "Sign Up: <url>" line: the first real event this was used on
    had a description that read "...And sign up here!
    https://..." — free-form prose, not a dedicated line — so requiring
    a strict format would have silently failed on the very first real
    use. This is a voluntary convention, not something the Calendar API
    exposes as its own field the way ATTACH does — there's no dedicated
    "signup link" field to pull from."""
    if not description:
        return None, description
    match = SIGNUP_RE.search(description)
    if not match:
        return None, description
    href = match.group(1).rstrip(".,!?)]}>'\"")
    remaining = (description[: match.start(1)] + description[match.start(1) + len(href) :]).strip()
    remaining = re.sub(r"[ \t]+", " ", remaining).strip()
    return href, remaining


DESCRIPTION_LIMIT = 200


def truncate_description(text, limit=DESCRIPTION_LIMIT):
    """Cuts text to at most `limit` characters, breaking at the last
    whole word instead of mid-word, and appending an ellipsis when it
    actually had to cut something. A blind text[:limit] slice (the
    previous approach) could end mid-word with nothing to signal
    anything was cut off — e.g. "...Join Virtually: Google Meet Or",
    stopping one word short of "Or dial..." with no ellipsis, reading
    like a broken/incomplete sentence rather than an intentionally
    shortened one."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(".,;:") + "…"


MEET_RE = re.compile(r"(?:[ \t]*[-–—:]+[ \t]*)?(https://meet\.google\.com/\S+)")


def extract_meet_href(description):
    """Finds a Google Meet link (https://meet.google.com/...) anywhere
    in a calendar event's Description — regardless of surrounding
    wording, since the meet.google.com domain alone is the signal, no
    nearby keyword needed — and returns (meet_href_or_None,
    remaining_description).

    The regex's optional leading group swallows a single separator
    (dash, em dash, or colon, plus surrounding spaces/tabs) immediately
    before the URL, e.g. Google Calendar's own default hybrid-meeting
    phrasing "Join Virtually: Google Meet — <link>", so removing the URL
    doesn't leave a dangling "— " behind. This has to be captured as
    part of the same match (not cleaned up afterward by checking what
    follows the removed URL) because by this point unescape_text has
    already turned every literal newline in the source into a plain
    space — so "ends right before a newline" is never actually true
    here, only "ends right before the URL" is reliable."""
    if not description:
        return None, description
    match = MEET_RE.search(description)
    if not match:
        return None, description
    href = match.group(1).rstrip(".,!?)]}>'\"")
    remaining = description[: match.start(0)] + description[match.start(1) + len(href) :]
    remaining = re.sub(r"[ \t]{2,}", " ", remaining).strip()
    return href, remaining


def is_pta_meeting_title(title):
    """A calendar event is the PTA's own recurring meeting, not some
    other event on the shared calendar, based on its title mentioning
    both words — the calendar has no dedicated field marking this.
    Mirrored (not imported — this script and src/build.py are
    independent) in src/build.py's own is_pta_meeting check, which
    applies the identical rule to config/pta-meetings.json's recap
    entries."""
    t = title.lower()
    return "pta" in t and "meeting" in t


def build_events_json(vevents, window_start, window_end, title_filter=None, max_events=MAX_EVENTS):
    occurrences = []
    for event in vevents:
        title = event.get("SUMMARY", "Untitled Event")
        if title_filter and not title_filter(title):
            continue
        start_time = event["DTSTART"]
        end_time = event.get("DTEND")
        all_day = event.get("DTSTART_ALLDAY", False)
        duration = (end_time - start_time) if end_time else None
        signup_href, description = extract_signup_href(event.get("DESCRIPTION"))
        meet_href, description = extract_meet_href(description)
        for occ_start in expand_occurrences(event, window_start, window_end):
            occ_end = occ_start + duration if duration else None
            occurrences.append({
                "start": occ_start,
                "title": title,
                "when": format_when(occ_start, occ_end, all_day, event.get("LOCATION")),
                "description": description,
                "signup_href": signup_href,
                "meet_href": meet_href,
                "attachments": event.get("ATTACH", []),
            })

    occurrences.sort(key=lambda o: o["start"])
    if max_events is not None:
        occurrences = occurrences[:max_events]

    out = []
    for i, occ in enumerate(occurrences):
        entry = {
            "day": f"{occ['start'].day:02d}",
            "month": MONTH_ABBR[occ["start"].month - 1],
            # ISO date (with year — day/month above deliberately omit it,
            # since the site only ever shows "23 Sep" for the current/next
            # occurrence, never a year). Not read by any page template;
            # this exists so an agent adding a calendar-linked announcement
            # (see .claude/skills/add-announcement/) can compute a real
            # expires date (event date + 1 day) without guessing the year.
            "date": occ["start"].date().isoformat(),
            "title": occ["title"],
            "when": occ["when"],
            "featured": i == 0,
        }
        if occ["attachments"]:
            entry["attachments"] = occ["attachments"]
        if occ["signup_href"]:
            entry["signup_href"] = occ["signup_href"]
        if occ["meet_href"]:
            entry["meet_href"] = occ["meet_href"]
        if i == 0:
            # The featured card always shows a description slot, so it
            # always gets one, even a generic one if the calendar didn't
            # set a real Description.
            entry["description"] = truncate_description(
                occ["description"] or f"Join us for {occ['title']} — see the full calendar for details."
            )
        elif occ["description"]:
            # Every other event on the quick-scan list shows its own
            # calendar Description too, if it set one — otherwise the
            # row just stays compact (day/time/title), no filler text.
            entry["description"] = truncate_description(occ["description"])
        out.append(entry)
    return out


FUNDRAISER_LOOKAHEAD_DAYS = 60  # "Coming up" on Ways to Give: starts within ~2 months
FUNDRAISER_LOOKBACK_DAYS = 120  # how far back a still-running fundraiser may have started
FUNDRAISER_TITLE_RE = re.compile(r"fundrais", re.I)


def format_date_range(start_date, end_date):
    """"Sep 25 – Oct 16", "Oct 3 – 10", or just "Nov 3" for one day."""
    first = f"{MONTH_ABBR[start_date.month - 1]} {start_date.day}"
    if end_date <= start_date:
        return first
    if end_date.month == start_date.month:
        return f"{first} – {end_date.day}"
    return f"{first} – {MONTH_ABBR[end_date.month - 1]} {end_date.day}"


def build_fundraiser_occurrences(vevents, today, local_tz=None):
    """Every calendar event with "fundraiser" in its title that's either
    running today or starts within FUNDRAISER_LOOKAHEAD_DAYS — for the
    "Current Fundraisers" section of the Ways to Give page.

    Separate from build_events_json because that one only ever sees
    occurrences that *start* on/after today, which drops exactly the
    case this exists for: a multi-week fundraiser (Joe Corbi's, Sep 25 –
    Oct 16) that's already running. `status` ("now"/"upcoming") is
    computed here, not in the build, so the file itself changes the day
    a fundraiser starts or ends — that change is what makes the hourly
    sync-events.yml redeploy."""
    window_start = dt.datetime.combine(today - dt.timedelta(days=FUNDRAISER_LOOKBACK_DAYS), dt.time.min)
    window_end = dt.datetime.combine(today + dt.timedelta(days=FUNDRAISER_LOOKAHEAD_DAYS), dt.time.max)
    out = []
    for event in vevents:
        title = event.get("SUMMARY", "")
        if not FUNDRAISER_TITLE_RE.search(title):
            continue
        start_time = event["DTSTART"]
        end_time = event.get("DTEND")
        all_day = event.get("DTSTART_ALLDAY", False)
        duration = (end_time - start_time) if end_time else None
        signup_href, description = extract_signup_href(event.get("DESCRIPTION"))
        for occ_start in expand_occurrences(event, window_start, window_end):
            occ_end = occ_start + duration if duration else occ_start
            start_date = occ_start.date()
            # An all-day event's DTEND is exclusive (the day *after*).
            end_date = (occ_end - dt.timedelta(days=1)).date() if all_day and duration else occ_end.date()
            end_date = max(end_date, start_date)
            if end_date < today or start_date > today + dt.timedelta(days=FUNDRAISER_LOOKAHEAD_DAYS):
                continue
            entry = {
                "title": title,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "dates": format_date_range(start_date, end_date),
                "when": format_when(occ_start, occ_start + duration if duration else None, all_day, event.get("LOCATION")),
                "status": "now" if start_date <= today else "upcoming",
            }
            if description:
                entry["description"] = truncate_description(description)
            if signup_href:
                entry["signup_href"] = signup_href
            if event.get("ATTACH"):
                entry["attachments"] = event["ATTACH"]
            out.append(entry)
    out.sort(key=lambda e: (e["start_date"], e["title"]))
    return out


def main():
    site = load_json("site.json")
    calendar_id = site["calendar"]["calendar_id"]
    local_tz = ZoneInfo(site["calendar"]["timezone"])

    try:
        raw = fetch_ics(calendar_id)
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  ! Could not fetch the calendar feed ({e}) — leaving config/events.json unchanged.")
        return

    vevents = parse_vevents(unfold(raw), local_tz)
    window_start = dt.datetime.combine(dt.date.today(), dt.time.min)
    window_end = window_start + dt.timedelta(days=LOOKAHEAD_DAYS)
    events = build_events_json(vevents, window_start, window_end)

    # A separate, uncapped-by-MAX_EVENTS feed of just the PTA's own
    # meeting occurrences. Without this, a PTA meeting more than
    # MAX_EVENTS (8) calendar-wide events away — easily true once a few
    # restaurant nights and a fall festival are also on the calendar —
    # would silently never reach config/events.json at all, even though
    # it's well within LOOKAHEAD_DAYS. Caught for real: the calendar's
    # Feb 2027 PTA meeting was invisible on the PTA Meetings page's
    # "Upcoming" section for exactly this reason.
    pta_window_end = window_start + dt.timedelta(days=PTA_MEETING_LOOKAHEAD_DAYS)
    pta_meeting_occurrences = build_events_json(
        vevents, window_start, pta_window_end, title_filter=is_pta_meeting_title, max_events=None
    )

    today = dt.datetime.now(local_tz).date()
    fundraiser_occurrences = build_fundraiser_occurrences(vevents, today)

    (CONFIG / "events.json").write_text(json.dumps(events, indent=2) + "\n")
    (CONFIG / "fundraiser-occurrences.json").write_text(json.dumps(fundraiser_occurrences, indent=2) + "\n")
    print(f"  synced {len(fundraiser_occurrences)} current/upcoming fundraiser(s) into config/fundraiser-occurrences.json")
    (CONFIG / "pta-meeting-occurrences.json").write_text(json.dumps(pta_meeting_occurrences, indent=2) + "\n")
    print(f"  synced {len(events)} upcoming event(s) from the calendar into config/events.json")
    print(
        f"  synced {len(pta_meeting_occurrences)} upcoming PTA meeting(s) into "
        "config/pta-meeting-occurrences.json"
    )


if __name__ == "__main__":
    main()
