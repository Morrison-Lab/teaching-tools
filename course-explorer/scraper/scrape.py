#!/usr/bin/env python3
"""Download WWU course offerings and catalog data from Banner "Browse Classes".

WWU retired its TimeTable/ClassFinder on 2025-10-07; the public replacement is
the Ellucian Banner 9 Student Registration self-service app, which exposes
JSON endpoints that need no login. This script pulls:

* every section of each term from --since onward (Banner lists terms back
  to Fall 2002), trimmed to the fields the explorer uses, into
  data/raw/sections/<term>.json;
* the course catalog for the newest term into data/raw/catalog.json;
* full course descriptions into data/raw/descriptions.json.

Banner's public search returns no student records beyond section-level
enrollment counts. Only each section's primary instructor (instructor of
record) is kept, by display name; secondary instructors (often graduate TAs),
e-mail addresses and Banner IDs are dropped. A graduate student who is the
instructor of record still appears, as on WWU's own Browse Classes.

Usage:
    python3 scraper/scrape.py                # this calendar year onward + catalog
    python3 scraper/scrape.py --since 201840 # Fall 2018 onward
    python3 scraper/scrape.py --all-terms    # every term back to 2002
    python3 scraper/scrape.py --terms 202640 202620

Term codes are YYYY plus 10 (Winter), 20 (Spring), 30 (Summer), 40 (Fall).
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests

BASE = "https://registration.banner.wwu.edu/StudentRegistrationSsb/ssb"
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
SECTIONS = RAW / "sections"
PAGE = 500
USER_AGENT = (
    "wwu-course-explorer/0.1 (+https://github.com/Morrison-Lab/teaching-tools; "
    "rate-limited)"
)
# Of the terms in range, the newest RECENT_TERMS are re-downloaded on every
# run (enrollment and instructors still change); older ones already on disk
# are treated as final.
RECENT_TERMS = 6


class Banner:
    """A Banner SSB session bound to one search mode and term."""

    def __init__(self, delay: float):
        self.delay = delay
        self.s = requests.Session()
        self.s.headers["User-Agent"] = USER_AGENT

    def _req(self, method: str, path: str, as_json: bool = False, **kw):
        """Send a request, retrying server errors and unparseable JSON."""
        for attempt in range(5):
            try:
                r = self.s.request(method, f"{BASE}/{path}", timeout=90, **kw)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {r.status_code}")
                r.raise_for_status()
                body = r.json() if as_json else r.text
                time.sleep(self.delay)
                return body
            except (requests.RequestException, ValueError) as e:
                wait = 2 ** (attempt + 1)
                print(f"  retry {path} in {wait}s: {e}", file=sys.stderr)
                time.sleep(wait)
        raise RuntimeError(f"giving up on {path}")

    def terms(self) -> list[dict]:
        terms = self._req("GET", "classSearch/getTerms", as_json=True,
                          params={"searchTerm": "", "offset": 1, "max": 1000})
        return sorted(terms, key=lambda t: t["code"], reverse=True)

    def select_term(self, term: str, mode: str) -> None:
        self._req("POST", f"term/search?mode={mode}", data={"term": term})

    def paged(self, path: str, term: str, key: str) -> list[dict]:
        """Fetch every page of a search, de-duplicated on `key`.

        Raises if Banner reports failure or the rows don't add up to its
        totalCount, so a bad response never replaces good data on disk.
        """
        rows: dict[str, dict] = {}
        offset, total = 0, None
        while total is None or offset < total:
            r = self._req("GET", path, as_json=True, params={
                "txt_term": term, "pageOffset": offset, "pageMaxSize": PAGE,
                "sortColumn": "subjectDescription", "sortDirection": "asc",
            })
            if r.get("success") is False:
                raise RuntimeError(f"{path} {term}: Banner reported failure")
            total = r.get("totalCount") or 0
            data = r.get("data") or []
            if not data:
                break
            for d in data:
                rows[str(d.get(key))] = d
            offset += len(data)
        if len(rows) != total:
            raise RuntimeError(f"{path} {term}: got {len(rows)} unique rows, "
                               f"Banner reported {total}")
        return list(rows.values())

    def description(self, term: str, subj: str, num: str) -> str:
        text = self._req("POST", "courseSearchResults/getCourseDescription",
                         data={"term": term, "subjectCode": subj,
                               "courseNumber": num})
        return clean_html(text)


def clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def days(mt: dict) -> str:
    names = [("monday", "M"), ("tuesday", "T"), ("wednesday", "W"),
             ("thursday", "R"), ("friday", "F"), ("saturday", "S"),
             ("sunday", "U")]
    return "".join(code for key, code in names if mt.get(key))


def trim_section(d: dict, attr_names: dict) -> dict:
    # Only the primary instructor (instructor of record) is kept. Banner also
    # lists secondary instructors, who are often graduate teaching
    # assistants, so they are dropped (see AGENTS.md).
    faculty = [f for f in d.get("faculty") or [] if f.get("primaryIndicator")]
    meetings = []
    for m in d.get("meetingsFaculty") or []:
        mt = m.get("meetingTime") or {}
        meetings.append([days(mt), mt.get("beginTime"), mt.get("endTime"),
                         mt.get("building"), mt.get("room")])
    attrs = []
    for a in d.get("sectionAttributes") or []:
        attr_names[a["code"]] = html.unescape(a.get("description") or "")
        attrs.append(a["code"])
    return {
        "crn": d.get("courseReferenceNumber"),
        "subj": d.get("subject"),
        "num": d.get("courseNumber"),
        "seq": d.get("sequenceNumber"),
        "title": html.unescape(d.get("courseTitle") or ""),
        "cred": [d.get("creditHourLow"), d.get("creditHourHigh")],
        "type": d.get("scheduleTypeDescription"),
        "method": d.get("instructionalMethod"),
        "methodDesc": d.get("instructionalMethodDescription"),
        "campus": d.get("campusDescription"),
        "enr": d.get("enrollment"),
        "max": d.get("maximumEnrollment"),
        "xlist": d.get("crossList"),
        "instr": [f["displayName"] for f in faculty if f.get("displayName")],
        "mtg": meetings,
        "attrs": attrs,
    }


def load_json(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def dump_json(path: Path, obj) -> None:
    """Write JSON atomically, so an interrupted run leaves the old file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":"),
                              sort_keys=False) + "\n")
    tmp.replace(path)


def scrape_terms(args) -> list[dict]:
    terms = Banner(args.delay).terms()
    for t in terms:
        t["description"] = html.unescape(t["description"])
    dump_json(RAW / "terms.json", terms)
    codes = [t["code"] for t in terms]
    if args.terms:
        wanted = args.terms
    else:
        in_range = [c for c in codes if args.all_terms or c >= args.since]
        have = {p.stem for p in SECTIONS.glob("*.json")}
        wanted = in_range[:RECENT_TERMS] + [c for c in in_range if c not in have]
    attr_path = RAW / "attributes.json"
    attr_names = load_json(attr_path, {})
    for code in dict.fromkeys(wanted):
        b = Banner(args.delay)
        b.select_term(code, "search")
        rows = b.paged("searchResults/searchResults", code,
                       key="courseReferenceNumber")
        sections = [trim_section(d, attr_names) for d in rows]
        sections.sort(key=lambda s: (s["subj"], s["num"], s["seq"] or ""))
        path = SECTIONS / f"{code}.json"
        old = len(load_json(path, []))
        if old and len(sections) < old // 2:
            # Sections get cancelled, but losing over half of a term at once
            # means a bad response, not a schedule change.
            raise RuntimeError(f"{code}: {len(sections)} sections, down from "
                               f"{old}; keeping the old file")
        dump_json(path, sections)
        print(f"{code}: {len(sections)} sections", file=sys.stderr)
    dump_json(attr_path, dict(sorted(attr_names.items())))
    return terms


def scrape_catalog(args, terms: list[dict]) -> None:
    term = terms[0]["code"]
    b = Banner(args.delay)
    b.select_term(term, "courseSearch")
    rows = b.paged("courseSearchResults/courseSearchResults", term, key="id")
    catalog = [{
        "subj": d["subject"],
        "num": d["courseNumber"],
        "title": html.unescape(d.get("courseTitle") or ""),
        "college": d.get("college"),
        "dept": d.get("department"),
        "subjDesc": html.unescape(d.get("subjectDescription") or ""),
        "cred": [d.get("creditHourLow"), d.get("creditHourHigh")],
        "termStart": d.get("termStart"),
        "termEnd": d.get("termEnd"),
        "short": html.unescape(d.get("courseDescription") or ""),
    } for d in rows]
    catalog.sort(key=lambda c: (c["subj"], c["num"]))
    dump_json(RAW / "catalog.json", catalog)
    print(f"catalog {term}: {len(catalog)} courses", file=sys.stderr)

    desc_path = RAW / "descriptions.json"
    descs = load_json(desc_path, {})
    todo = [c for c in catalog
            if args.refresh_descriptions or f"{c['subj']} {c['num']}" not in descs]
    if args.max_descriptions is not None:
        todo = todo[:args.max_descriptions]
    for i, c in enumerate(todo, 1):
        key = f"{c['subj']} {c['num']}"
        try:
            descs[key] = b.description(term, c["subj"], c["num"])
        except RuntimeError as e:
            print(f"  {key}: {e}", file=sys.stderr)
        if i % 200 == 0:
            dump_json(desc_path, dict(sorted(descs.items())))
            print(f"  descriptions {i}/{len(todo)}", file=sys.stderr)
    dump_json(desc_path, dict(sorted(descs.items())))


def term_code(value: str) -> str:
    if not re.fullmatch(r"\d{4}[1-4]0", value):
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a term code like 202640")
    return value


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--terms", nargs="+", type=term_code, help="term codes to (re)download")
    p.add_argument("--since", type=term_code,
                   default=f"{date.today().year}10",
                   help="first term code to download (default: Winter of "
                        "this calendar year)")
    p.add_argument("--all-terms", action="store_true",
                   help="download every term Banner lists, ignoring --since")
    p.add_argument("--skip-sections", action="store_true")
    p.add_argument("--skip-catalog", action="store_true")
    p.add_argument("--refresh-descriptions", action="store_true")
    p.add_argument("--max-descriptions", type=int)
    p.add_argument("--delay", type=float, default=0.3,
                   help="seconds to wait between requests (default 0.3)")
    args = p.parse_args()
    if args.skip_sections:
        terms = Banner(args.delay).terms()
    else:
        terms = scrape_terms(args)
    if not args.skip_catalog:
        scrape_catalog(args, terms)


if __name__ == "__main__":
    main()
