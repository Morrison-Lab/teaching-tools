# CLAUDE.md

Read [AGENTS.md](AGENTS.md) before running anything here.
In particular, never run `studentwork.py`: it downloads student submissions (FERPA).

Test the assignment sync with `python3 canvas/tests/test_sync_assignments.py`,
the module file upload with `python3 canvas/tests/test_upload_module_files.py`,
and the calendar sync with `python3 canvas/tests/test_sync_calendar.py`.

## Answer keys go up as a PDF and an HTML file

Ezra, 2026-11-10: "so that students can examine 3d graphs in the solutions files, we should start uploading html versions of the solutions files in addition to the pdf versions, using the `embed-resources: true` option"
([teaching-tools#18](https://github.com/Morrison-Lab/teaching-tools/issues/18)).
The HTML is the course repository's self-contained render of the key
(mlg sets `embed-resources: true` in `_quarto-solution.yml`, [mlg#350](https://github.com/Morrison-Lab/mlg/issues/350)).
`sync_assignments.py` uploads the same-stem `.html` beside a PDF `solution:` and stops if it is missing,
and `upload_module_files.py` refuses a PDF whose path mentions "solution" unless its `.html` is passed too.

## CI

`tests.yml` runs the assignment sync and calendar sync self-tests.
The rest are thin callers of reusable workflows in
[`Morrison-Lab/gha`](https://github.com/Morrison-Lab/gha), pinned at `@v2`, copied from
`Morrison-Lab/canvas`: `claude-review.yml` (automated PR review), `claude-bot.yml`
(`@claude` mentions), `check-secrets.yml` (gitleaks over the full history),
`check-typos.yml`, `check-junk-files.yml`, `lint-workflows.yml` (actionlint and zizmor,
configured by `.github/zizmor.yml`), and the warn-only `check-new-line-breaks.yml` and
`check-ai-tells.yml`. `.github/dependabot.yml` keeps the action pins current.

The WWU course explorer moved to [`Morrison-Lab/swc`](https://github.com/Morrison-Lab/swc).

`.claude/settings.json` enables the lab's `ai-config` plugin for Claude Code sessions here.
It also allows `canvas/upload_module_files.py`, so uploads that Ezra's deliverable asks already cover do not wait for a typed "go".
A project-level rule applies only when the session's working directory is this checkout,
so start a Canvas upload session here (on cf463-02, `/home/morri313/Documents/GitHub/teaching-tools`)
and run the script by the relative path `canvas/upload_module_files.py`.
