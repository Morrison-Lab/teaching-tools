# WWU Course Explorer

A search site for Western Washington University courses, modeled on Stanford's
[ExploreCourses](https://explorecourses.stanford.edu/).
Search by code, title, keyword, instructor or department,
filter by subject, term, level, attribute (GUR, writing proficiency, ...) and delivery mode,
and see every section of a course in the loaded terms, with its instructor, meeting times and enrollment.

## Data sources

| Source | What it gives | How |
|---|---|---|
| [Browse Classes](https://registration.banner.wwu.edu/StudentRegistrationSsb/ssb/term/termSelection?mode=search) (Ellucian Banner 9) | Sections for every term from Fall 2002 on: instructor, times, rooms, enrollment, delivery, attributes; the course catalog with college, department and descriptions | Public JSON endpoints, no login |
| [University Catalog](https://catalog.wwu.edu/) (Acalog) | Official course pages | Linked from each course; the site blocks scripted requests, so it is not scraped |
| [`data/syllabi.csv`](data/syllabi.csv) | Syllabus and course-material links | Curated by hand |

WWU retired its TimeTable/ClassFinder on 2025-10-07; Browse Classes replaced it.

By default the scraper downloads terms from Winter of the current calendar year onward.
Earlier terms are one flag away (`--since 201840`, or `--all-terms` for everything since 2002).

### Privacy

Banner's public search has no student data beyond section enrollment counts.
The scraper keeps only each section's primary instructor, by name.
It drops secondary instructors, who are often student teaching assistants,
and instructor e-mail addresses and Banner IDs.

## Run it locally

```sh
pip install requests
python3 scraper/scrape.py      # sections, catalog, descriptions -> data/raw/
python3 scraper/build.py       # -> site/data/courses.json
python3 -m http.server -d site 8000
```

The first run fetches about 5,000 course descriptions one at a time and takes a couple of hours;
later runs fetch only new courses.
`--max-descriptions N` caps that for a quick test.

## Publishing

[`.github/workflows/course-explorer.yml`](../.github/workflows/course-explorer.yml)
re-scrapes daily, rebuilds, and deploys `site/` to GitHub Pages.
It needs **Settings > Pages > Source: GitHub Actions** turned on once.
Run it by hand from the Actions tab, optionally with a `since` term code to load more history.

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
