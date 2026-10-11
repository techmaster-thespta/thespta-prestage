#!/usr/bin/env python3
"""
Move expired announcements and featured event pages out of the live
config and into archive/, for future reference.

  config/announcements.json  -> archive/announcements.json
  config/event-pages.json    -> archive/event-pages.json
  assets/flyers/<file>       -> archive/flyers/<file>   (their flyers)

"Expired" means today (in the PTA's own timezone) is past the entry's
`expires` date — the last day it's shown, inclusive. For an event page
with no explicit `expires`, that's the day the event ends; see
event_page_expires() in src/build.py, which this reuses so the two can
never disagree about what counts as expired.

Run by both .github/workflows/deploy.yml (every push) and
sync-events.yml (hourly), right before the build. archive/ is never
copied into the deployed site, so an archived page stops being
published on that same run — src/build.py also clears pages/events/ on
every build so the old HTML can't linger. The build filters expired
entries on its own too; this script is what makes it permanent and
keeps the live config files short.

A flyer is only moved if nothing still live references it (an event
page and an announcement can share one). Idempotent: running it again
with nothing expired changes nothing.

Stdlib only.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from build import event_page_expires, is_expired, site_today  # noqa: E402

CONFIG = ROOT / "config"
ARCHIVE = ROOT / "archive"
FLYERS = ROOT / "assets" / "flyers"


def load(path):
    return json.loads(path.read_text()) if path.exists() else []


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def announcement_flyers(a):
    """Flyer paths (relative to assets/flyers/) an announcement uses. Its
    `icon_filename` lives in the shared assets/images/ and is left alone —
    icons are small and commonly reused across announcements."""
    return [os.path.normpath(f"announcements/{a['flyer_filename']}")] if a.get("flyer_filename") else []


def event_page_flyers(e):
    names = [e["flyer_filename"]] if e.get("flyer_filename") else []
    names += [f["filename"] for f in e.get("extra_flyers", [])]
    return [os.path.normpath(n) for n in names]


def main():
    site = json.loads((CONFIG / "site.json").read_text())
    today = site_today(site)

    kinds = [
        ("announcements.json", lambda a: a.get("expires"), announcement_flyers),
        ("event-pages.json", event_page_expires, event_page_flyers),
    ]

    live, expired = {}, {}
    for name, expires_of, _ in kinds:
        entries = load(CONFIG / name)
        live[name] = [x for x in entries if not is_expired(expires_of(x), today)]
        expired[name] = [x for x in entries if is_expired(expires_of(x), today)]

    if not any(expired.values()):
        print("Nothing expired — no changes.")
        return

    still_used = {f for name, _, flyers_of in kinds for x in live[name] for f in flyers_of(x)}

    for name, expires_of, flyers_of in kinds:
        if not expired[name]:
            continue
        archive_path = ARCHIVE / name
        archived = load(archive_path)
        for x in expired[name]:
            archived.append({**x, "archived_on": today.isoformat()})
            label = x.get("title") or x.get("text", "")
            print(f"  archived from config/{name}: {label} (expired {expires_of(x)})")
            for rel in flyers_of(x):
                src = FLYERS / rel
                if rel in still_used or not src.exists():
                    continue
                dest = ARCHIVE / "flyers" / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                src.replace(dest)
                print(f"    moved flyer assets/flyers/{rel} -> archive/flyers/{rel}")
        dump(archive_path, archived)
        dump(CONFIG / name, live[name])


if __name__ == "__main__":
    main()
