# CLAUDE.md

Read [AGENTS.md](AGENTS.md) before running anything here.
In particular, never run `studentwork.py`: it downloads student submissions (FERPA).

Test the assignment sync with `python3 canvas/tests/test_sync_assignments.py`,
and the module file upload with `python3 canvas/tests/test_upload_module_files.py`.

## CI

`tests.yml` runs the assignment sync self-test.
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
