# Handoff — monday-github-issues-sync

**Last updated:** 2026-07-26
**Status:** Built, published, tested, and validated against a live board.
No known open defects.

This is a development handoff: the context a fresh contributor (human or agent)
needs that the code and docs do not already carry. It is deliberately not a
tutorial — see `README.md` to install and `SKILL.md` for how the skill works.

## What this is

A Claude Code skill that mirrors a GitHub repo's issues and pull requests into a
monday.com board (one-way, GitHub → monday), so PM can see development activity
without living in GitHub.

- **Latest release:** v1.6.0
- **Invoked as:** `/monday-github-issues-sync`

**Do not re-read the design from this document.** `SKILL.md` is the entry point;
`references/*.md` carry the mechanics. Everything below is context those files do
*not* capture.

## Current state — nothing is pending

| Item | State |
|---|---|
| Skill + docs + scripts | complete, v1.6.0, 8 portability checks passing |
| Test suite | 75 tests, 99% coverage on both scripts, gates releases |
| Live backfill | complete: 26 items, 50 feed entries, all assigned |
| Doubled-link repair (17 entries) | done, verified by reading bodies back |
| Test board placeholders / 2nd board | deleted |

Board id and repo slug live in `.monday-sync/*.json` in the working copy
(gitignored, never committed).

## Testing

```bash
python3 -m unittest discover -s tests    # no dependencies
PYTHONPATH=tests pytest tests/           # pytest also works
```

Stdlib `unittest` on purpose: verifying a cloned skill should not require an
install. Coverage was measured with a throwaway venv (`pytest` + `pytest-cov`);
it is not a project dependency.

`tests/helpers.py` loads the hyphenated scripts by path, so the tests exercise
the exact files that ship.

**Tests named `test_regression_*` each encode a bug that reached a live board.**
All seven were mutation-tested — the fix was reverted and the test confirmed to
fail. If one of these fails you have reintroduced a real defect; do not relax or
delete it.

`packaging/release.sh` runs the suite and refuses to release on failure.

## Hard-won facts about the monday API

Established empirically; documented in `references/board-schema.md` and
`references/update-format.md`. Listed here so nobody re-derives them.

1. **`create_update` accepts `original_creation_date` and silently ignores it.**
   Three formats tested; `created_at` is always now. Backdating is impossible on
   this path. Real time lives in the bold `[... UTC]` body prefix and the item's
   date columns — never build a monday view on update timestamps.
2. **monday strips HTML comments** from update bodies (also `<br/>` → `<br>`,
   adds `target`/`rel` to anchors). An earlier `<!-- gh-event:KEY -->` marker
   scheme did not survive. Feed identity now comes from the footer link's
   `#issuecomment-<id>` href.
3. **Generated column ids do not match the requested type** — `status` returns
   `color_*`, `numbers` returns `numeric_*`. Never construct an id.
4. **Date columns: compare `value`, never `text`.** `text` renders in
   account-local time; comparing it to GitHub UTC makes every item look changed
   forever.
5. **`gh api` prints its error body to stdout**, so a 404 yields a JSON blob that
   passes a `-n` test. Validate shape, not emptiness.
6. **`gh repo view --json issues` counts only OPEN issues** — understated the
   test repo 6 vs 18.
7. **`edit_update(id, body)` and `delete_update(id)` exist** — used to repair
   posted entries in place without deleting anything.

## Environment / permission gotchas

- The auto-mode classifier **intermittently blocks** monday MCP writes.
  `create_items` (batch) was blocked outright; single `create_item` worked.
  `create_column` was refused on ~half of identical calls at one point. If writes
  start failing, it is the classifier, not the API — stop and ask the user to
  allow the tools rather than retrying in a loop.
- `all_api_write` works for `delete_board` / `delete_item` / `edit_update`.
- The skill declares **zero destructive monday tools** in `allowed-tools` by
  design — structurally incapable of deleting. Do not add any.

## Conventions the user has asked for explicitly

- **Never auto-delete.** Every removal is proposed and waits for a yes. If a user
  reports something deleted, point them at their monday.com admin — deleted items
  sit in the recycle bin and admins can restore them. Do **not** re-sync to
  "rebuild" first; that makes the restore land as a duplicate.
- **No bot labelling.** Authors are attributed by GitHub login with a trailing
  `[bot]` stripped. No badge, glyph, suffix, or separate group, and no formatting
  branches on bot-ness. `options.automationAuthor` re-attributes `[bot]` authors
  to a configured login (an *ownership* view, not an authorship claim). The lint
  fails on bot-labelling constructs; tests assert a bot entry and a human entry
  render identically.
- **Portability is enforced.** No GitHub/monday account, org, repo, board,
  column, or user id hardcoded. `./packaging/verify-portable.sh` has 8 checks,
  each negative-tested. Upstream slug allowed only in README/CLAUDE/INSTALL and
  `scripts/update-skill.sh`.
- **Releases:** `./packaging/release.sh X.Y.Z --publish` — tests, lint, VERSION
  bump, SKILL.md frontmatter stamp, `dist/` rebuild, versioned + latest zips,
  tag, push, GitHub release. Blocks on test or lint failure.

## Process lessons — these cost real time

- **`str.replace` in a patch script silently does nothing when the pattern does
  not match, and the script still prints "done".** This happened **three times**
  this session: two doc-wiring edits and the release-gate fix were all no-ops I
  caught only by grepping afterward. Prefer the Edit tool (errors on mismatch) or
  add `assert old in s` to every replace.
- **`cmd | tail` exits with `tail`'s status.** My first release gate piped the
  test run, so a failing suite exited 0 and shipped an artifact. Capture status
  explicitly. There is a comment in `release.sh` warning against reintroducing
  the pipe.
- **Test the path you are shipping.** The paste-the-URL install flow was written
  and asserted working while the repo was private — it 404'd. Only found when the
  user asked directly.
- **A test that matches on wording is weaker than it looks.** The first
  single-footer-link assertion matched exact label text; a reworded duplicate
  passed. Rewritten to a wording-independent invariant (an entry links to its own
  URL exactly once).
- **Cost shape:** building and testing dominated; a real sync is ~90 API
  calls. Feed-entry work is the expensive part because each ~1.4 KB body
  round-trips through the model's context twice.

## Likely next steps (none blocking)

- Exercise **Step 1 (MCP absent)** and the **new-board offer** against a live
  session — reasoned but untested.
- Recurring sync via the `schedule` skill (`options.autoApprove: true` skips the
  plan confirmation and the Step 0 update check).
- Consider `options.excludeAuthors` — 7 of 8 PRs on the test repo are dependency
  bumps and dominate the PR rows.
- `syncCommits` and `syncLabelEvents` are off by default and unexercised.
- No integration test touches the monday MCP; everything MCP-side was validated
  by hand. A fake-MCP harness would close that gap if the skill grows.

## Suggested skills

- **`ecc:code-reviewer`** — a fresh pass over `scripts/`, `packaging/`, and the
  test suite. The renderer carries six accumulated bug fixes; worth an
  independent read before wider distribution.
- **`ecc:security-reviewer`** — only if credential or webhook handling is added.
  Nothing currently handles secrets (writes go through the MCP server; no tokens
  stored).
- **`/browse` (gstack)** — for visually QA'ing the rendered monday feed. Every
  rendering bug this session was found by reading HTML, not by looking at the
  board; a visual pass may still surface layout issues the tests cannot.

Skills that are **no longer needed**: `ecc:tdd-guide` and `ecc:python-reviewer`
were previously suggested because the scripts had zero tests. That gap is closed
(75 tests, 99% coverage, mutation-verified, release-gated).

Avoid `ecc:doc-updater` — the docs are dense, deliberately worded, and encode
test results and negative findings. Regenerating them would lose that.
