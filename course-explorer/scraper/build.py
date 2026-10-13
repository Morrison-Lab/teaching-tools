#!/usr/bin/env python3
"""Build the explorer's search index from the files scrape.py downloads.

Reads data/raw/ (terms, sections, catalog, descriptions, attributes) and
data/syllabi.csv, and writes site/data/courses.json: one record per course,
with its catalog details and every section in the downloaded terms.

Usage:
    python3 scraper/build.py
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "site" / "data" / "courses.json"


def load(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def credits(low, high) -> str:
    def fmt(x):
        return f"{x:g}" if isinstance(x, (int, float)) else ""
    if high not in (None, low):
        return f"{fmt(low)}-{fmt(high)}"
    return fmt(low)


def level(num: str) -> int | None:
    digits = "".join(ch for ch in num if ch.isdigit())
    return int(digits[0]) * 100 if digits else None


def main() -> None:
    terms = load(RAW / "terms.json", [])
    term_names = {t["code"]: t["description"].replace(" (View Only)", "")
                  for t in terms}
    attrs = load(RAW / "attributes.json", {})
    catalog = load(RAW / "catalog.json", [])
    descs = load(RAW / "descriptions.json", {})

    courses: dict[str, dict] = {}

    def course(subj: str, num: str) -> dict:
        key = f"{subj} {num}"
        if key not in courses:
            courses[key] = {"id": key, "subj": subj, "num": num,
                            "level": level(num), "title": "", "subjDesc": "",
                            "dept": "", "college": "", "cred": "", "desc": "",
                            "attrs": [], "offered": [], "sections": [],
                            "syllabi": []}
        return courses[key]

    for c in catalog:
        rec = course(c["subj"], c["num"])
        rec.update(title=c["title"], subjDesc=c["subjDesc"],
                   dept=c["dept"] or "", college=c["college"] or "",
                   cred=credits(*c["cred"]),
                   desc=descs.get(rec["id"]) or c["short"] or "")

    term_files = sorted((RAW / "sections").glob("*.json"))
    loaded_terms = [p.stem for p in term_files]
    course_attrs = defaultdict(set)
    methods: dict[str, str] = {}
    for path in term_files:
        term = path.stem
        for s in load(path, []):
            if s.get("method"):
                methods[s["method"]] = s.get("methodDesc") or s["method"]
            rec = course(s["subj"], s["num"])
            rec["title"] = rec["title"] or s["title"]
            rec["cred"] = rec["cred"] or credits(*s["cred"])
            rec["desc"] = rec["desc"] or descs.get(rec["id"], "")
            if term not in rec["offered"]:
                rec["offered"].append(term)
            course_attrs[rec["id"]].update(s["attrs"])
            rec["sections"].append({
                "term": term, "seq": s["seq"], "crn": s["crn"],
                "title": s["title"] if s["title"] != rec["title"] else "",
                "type": s["type"], "method": s["method"],
                "campus": s["campus"], "instr": s["instr"], "mtg": s["mtg"],
                "enr": s["enr"], "max": s["max"], "attrs": s["attrs"],
            })

    for key, codes in course_attrs.items():
        courses[key]["attrs"] = sorted(codes)

    syllabi_path = ROOT / "data" / "syllabi.csv"
    if syllabi_path.exists():
        with syllabi_path.open(newline="") as f:
            rows = list(csv.DictReader(
                line for line in f if not line.startswith("#")))
        for n, r in enumerate(rows, 1):
            key = " ".join((r.get("course") or "").split()).upper()
            url = (r.get("url") or "").strip()
            if not re.match(r"https?://", url, re.I):
                sys.exit(f"syllabi.csv row {n}: url must start with "
                         f"http:// or https:// (got {url!r})")
            if key not in courses:
                print(f"warning: syllabi.csv row {n}: no course {key!r}",
                      file=sys.stderr)
                continue
            courses[key]["syllabi"].append(
                {k: (r.get(k) or "").strip() for k in
                 ("term", "instructor", "url", "label")})

    ordered = sorted(courses.values(), key=lambda c: (c["subj"], c["num"]))
    out = {
        "terms": [{"code": c, "name": term_names.get(c, c)}
                  for c in loaded_terms],
        "attributes": attrs,
        "methods": dict(sorted(methods.items())),
        "catalogTerm": terms[0]["code"] if terms else "",
        "courses": ordered,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    tmp.replace(OUT)
    n_sections = sum(len(c["sections"]) for c in ordered)
    print(f"{len(ordered)} courses, {n_sections} sections, "
          f"{len(loaded_terms)} terms -> {OUT.relative_to(ROOT)} "
          f"({OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
