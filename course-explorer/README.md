# WWU Course Explorer

A search site for Western Washington University courses, modeled on Stanford's
[ExploreCourses](https://explorecourses.stanford.edu/).
Search by code, title, keyword, instructor or department,
filter by subject, term, level, attribute (GUR, writing proficiency, ...) and delivery mode,
and see every section of a course in the loaded terms, with its instructor, meeting times and enrollment.

## Data sources

| Source | What it gives | How |
|---|---|---|
| [Browse Classes](https://registration.banner.wwu.edu/StudentRegistrationSsb/ssb/term/termSelection?mode=search) (Ellucian Banner 9) | Sections for any term back to Fall 2002: instructor, times, rooms, enrollment, delivery, attributes; the course catalog with college, department and descriptions | Public JSON endpoints, no login |
| [University Catalog](https://catalog.wwu.edu/) (Acalog) | Official course pages | Linked from each course; the site blocks scripted requests, so it is not scraped |
| [`data/syllabi.csv`](data/syllabi.csv) | Syllabus and course-material links | Curated by hand |

WWU retired its TimeTable/ClassFinder on 2025-10-07; Browse Classes replaced it.

By default the scraper downloads terms from Winter of the current calendar year onward.
Earlier terms are one flag away (`--since 201840`, or `--all-terms` for everything since 2002).

### Privacy

Banner's public search has no student data beyond section enrollment counts.
The scraper keeps only each section's primary instructor (the instructor of record), by name.
It drops secondary instructors, who are often graduate teaching assistants,
and instructor e-mail addresses and Banner IDs.
A graduate student who is the instructor of record still appears, as on WWU's own Browse Classes.

## Run it locally

```sh
pip install requests
python3 scraper/scrape.py      # sections, catalog, descriptions -> data/raw/
python3 scraper/build.py       # -> site/data/courses.json
python3 -m http.server -d site 8000
```

Course descriptions are fetched one at a time (about 1.5 seconds each) and cached in
`data/raw/descriptions.json`, which is committed, so a run fetches only courses missing from it.
`--max-descriptions N` caps that for a quick test.

## Publishing

[`.github/workflows/course-explorer.yml`](../.github/workflows/course-explorer.yml)
re-scrapes daily, rebuilds, and deploys `site/` to GitHub Pages.
It needs **Settings > Pages > Source: GitHub Actions** turned on once.
Run it by hand from the Actions tab, optionally with a `since` term code to load more history.

Downloaded terms carry over between runs in the Actions cache, not in git.
If that cache is evicted (GitHub drops caches unused for 7 days),
the next run rebuilds from `since` only, and older terms loaded by hand drop off the site
until a run with that `since` is repeated.
If a term's new download has under half the sections of the cached copy,
the scraper keeps the old copy, finishes the other terms, and then fails the run,
so a truncated schedule is never published.
If the drop is real, run the workflow by hand with **allow_shrink** checked.

## Adding syllabi

Add a row to [`data/syllabi.csv`](data/syllabi.csv):

```csv
course,term,instructor,url,label
BIOL 204,202640,"Doe, Jane",https://example.edu/biol204-syllabus.pdf,Syllabus
```

Link only public pages, and nothing that names a student.

## Layout

- [`scraper/scrape.py`](scraper/scrape.py): downloads from Banner into `data/raw/`
- [`scraper/build.py`](scraper/build.py): merges sections, catalog, descriptions and syllabi into one index
- [`site/`](site/): static page (`index.html`, `app.js`, `style.css`) searching the index in the browser with [MiniSearch](https://lucaong.github.io/minisearch/)
