# CLAUDE.md

Read [AGENTS.md](AGENTS.md) before running anything here.
In particular, never run `studentwork.py`: it downloads student submissions (FERPA).

Test the assignment sync with `python3 canvas/tests/test_sync_assignments.py`.

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
