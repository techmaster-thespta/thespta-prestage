#!/usr/bin/env python3
"""
Validates the built site. Run after `python3 src/build.py`:

    python3 test/validate_build.py

Checks, per generated page in /pages:
  1. No unresolved {{placeholder}} markers were left behind.
  2. HTML tags are balanced (no unclosed/mismatched tags).
  3. Every link to another page on this site (nav menu included) points
     at a page that was actually built — so an expired featured event
     page can never be removed while a menu link to it stays behind.

Exits non-zero (and prints what's wrong) if anything fails — this is what
gates the GitHub Actions workflow before it pushes anything to Drive.
No dependencies beyond the Python 3 standard library.
"""
import glob
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = ROOT / "pages"

PLACEHOLDER = re.compile(r"\{\{\s*[\w.]+\s*\}\}")
VOID_TAGS = {"br", "img", "input", "hr", "link", "meta", "area", "base", "col", "embed", "source", "track", "wbr"}


class TagBalanceChecker(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.errors = []
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if href:
                self.hrefs.append(href)
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        if not self.stack:
            self.errors.append(f"extra closing </{tag}>")
            return
        if self.stack[-1] == tag:
            self.stack.pop()
        elif tag in self.stack:
            self.errors.append(f"mismatch: expected </{self.stack[-1]}>, got </{tag}>")
            while self.stack and self.stack[-1] != tag:
                self.stack.pop()
            if self.stack:
                self.stack.pop()
        else:
            self.errors.append(f"unmatched closing </{tag}>")


def check_page(path):
    text = path.read_text()
    problems = []

    leftover = sorted(set(PLACEHOLDER.findall(text)))
    if leftover:
        problems.append(f"unresolved placeholders: {leftover}")

    checker = TagBalanceChecker()
    checker.feed(text)
    if checker.errors:
        problems.append(f"tag errors: {checker.errors}")
    if checker.stack:
        problems.append(f"unclosed tags at end of file: {checker.stack}")

    broken = sorted({h for h in checker.hrefs if is_internal_page_link(h) and not link_target(path, h).exists()})
    if broken:
        problems.append(f"links to pages that don't exist: {broken}")

    return problems


def is_internal_page_link(href):
    """A relative link to another page here: ends in .html, or is a
    directory root like "./" or "../" (the Home page). Off-site links,
    mailto/tel, in-page #anchors and image/flyer files are skipped."""
    if re.match(r"^[a-z][a-z0-9+.-]*:", href, re.I) or href.startswith(("#", "//", "/")):
        return False
    target = href.split("#", 1)[0].split("?", 1)[0]
    return target.endswith(".html") or target.endswith("/") or target in (".", "..")


def link_target(page, href):
    target = href.split("#", 1)[0].split("?", 1)[0]
    resolved = (page.parent / target).resolve()
    return resolved / "index.html" if target.endswith("/") or target in (".", "..") else resolved


def main():
    if not PAGES.is_dir():
        print("No /pages directory found — run `python3 src/build.py` first.")
        return 1

    page_files = sorted(glob.glob(str(PAGES / "**" / "*.html"), recursive=True))
    if not page_files:
        print("No generated pages found in /pages — run `python3 src/build.py` first.")
        return 1

    failed = False
    for f in page_files:
        path = Path(f)
        problems = check_page(path)
        if problems:
            failed = True
            print(f"FAIL  {path.relative_to(ROOT)}")
            for p in problems:
                print(f"      - {p}")
        else:
            print(f"OK    {path.relative_to(ROOT)}")

    if failed:
        print("\nValidation failed.")
        return 1

    print(f"\nAll {len(page_files)} pages passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
