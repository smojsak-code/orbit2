#!/usr/bin/env python3
"""
Orbit2 HTML structural checker (R1-T09 instruction #56).

Checks any Orbit2 HTML surface (dashboard.html, web/index_template.html)
for two classes of problem that are otherwise invisible until a user
clicks the wrong thing in a browser:

1. Duplicate element IDs. Two elements sharing an `id` is always a bug in
   this codebase — every `document.getElementById(...)` call in these
   files assumes IDs are unique, and a duplicate silently makes the
   *first* matching element win, leaving the second one dead code that
   looks like it should work.

2. Missing navigation targets. Both HTML files declare a
   `const VIEWS = ['home', 'dashboard', ...]` array and a `switchView()`
   function that toggles `#view<Capitalized>` and `#tab<Capitalized>`
   elements for each entry. If a view name is added to VIEWS without its
   matching `#viewX`/`#tabX` element (or vice versa — an orphaned view
   container nothing ever switches to), clicking that tab does nothing and
   nothing prints an error to say why.

Used both by tests/test_html_checks.py (pytest) and
scripts/validate_release.py (release gate). Requires BeautifulSoup4.

Usage:
    python3 scripts/check_html.py dashboard.html web/index_template.html
"""
import argparse
import os
import re
import sys

from bs4 import BeautifulSoup

VIEWS_ARRAY_RE = re.compile(r"const\s+VIEWS\s*=\s*\[([^\]]*)\]")
VIEW_NAME_RE = re.compile(r"""['"]([a-zA-Z0-9_]+)['"]""")


def _capitalize(view_name):
    return view_name[0].upper() + view_name[1:]


def find_duplicate_ids(soup):
    """Return {id: count} for every id="..." attribute that appears more
    than once in the document."""
    counts = {}
    for el in soup.find_all(attrs={"id": True}):
        counts[el["id"]] = counts.get(el["id"], 0) + 1
    return {i: c for i, c in counts.items() if c > 1}


def extract_views_array(html_text):
    """Pull the view names out of `const VIEWS = [...]`. Returns [] if no
    such array is declared in this file (some Orbit2 HTML surfaces, like a
    future standalone page, might not have one)."""
    m = VIEWS_ARRAY_RE.search(html_text)
    if not m:
        return []
    return VIEW_NAME_RE.findall(m.group(1))


def check_nav_targets(html_text, soup):
    """For every entry in VIEWS, confirm both #view<Cap> and #tab<Cap>
    exist. Returns a list of human-readable problem strings (empty if
    everything required is present)."""
    problems = []
    views = extract_views_array(html_text)
    if not views:
        return problems  # no VIEWS array in this file — nothing to check

    all_ids = {el.get("id") for el in soup.find_all(attrs={"id": True})}
    for v in views:
        view_id = "view" + _capitalize(v)
        tab_id = "tab" + _capitalize(v)
        if view_id not in all_ids:
            problems.append(f"VIEWS includes '{v}' but no element has id=\"{view_id}\"")
        if tab_id not in all_ids:
            problems.append(f"VIEWS includes '{v}' but no element has id=\"{tab_id}\"")
    return problems


def check_file(path):
    """Return {"duplicate_ids": {...}, "missing_nav_targets": [...]} for
    one HTML file. Both empty means the file is clean."""
    with open(path, encoding="utf-8") as f:
        html_text = f.read()
    soup = BeautifulSoup(html_text, "html.parser")
    return {
        "duplicate_ids": find_duplicate_ids(soup),
        "missing_nav_targets": check_nav_targets(html_text, soup),
    }


def format_report(path, result):
    lines = []
    if result["duplicate_ids"]:
        lines.append(f"{path}: duplicate element ID(s):")
        for id_, count in sorted(result["duplicate_ids"].items()):
            lines.append(f"  id=\"{id_}\" appears {count} times")
    if result["missing_nav_targets"]:
        lines.append(f"{path}: missing navigation target(s):")
        for p in result["missing_nav_targets"]:
            lines.append(f"  {p}")
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="HTML files to check")
    args = ap.parse_args()

    any_problems = False
    for path in args.files:
        if not os.path.exists(path):
            print(f"{path}: file does not exist")
            any_problems = True
            continue
        result = check_file(path)
        lines = format_report(path, result)
        if lines:
            any_problems = True
            for line in lines:
                print(line)
        else:
            print(f"{path}: OK ({len(extract_views_array(open(path).read()))} nav target(s) checked)")

    sys.exit(1 if any_problems else 0)


if __name__ == "__main__":
    main()
