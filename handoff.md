# Handoff — monday-github-issues-sync

**Last updated:** 2026-08-06
**Status:** Built, published, tested, and validated against a live board.
No known open defects.

**1.8.1** fixed the one defect found since: closes and merges never reached the
Updates feed. See *Hard-won facts* #8 — it is the most instructive bug in the
project's history, because every individual piece was correct and tested.

**1.8.2** closed the same class of hole one layer down: `event_key()` silently
fell back to `state:<kind>@<at>` for an id-keyed event built without an `id`,
yielding a plausible key that matches nothing and re-posts entries already on
the board. It now raises. Caught as a near-miss on a live run — see *Process
lessons*.

This is a development handoff: the context a fresh contributor (human or agent)
needs that the code and docs do not already carry. It is deliberately not a
tutorial — see `README.md` to install and `SKILL.md` for how the skill works.

## What this is

A Claude Code skill that mirrors a GitHub repo's issues and pull requests into a
monday.com board (one-way, GitHub → monday), so PM can see development activity
without living in GitHub.

- **Latest release:** v1.8.2
- **Invoked as:** `/monday-github-issues-sync`

**Do not re-read the design from this document.** `SKILL.md` is the entry point;
`references/*.md` carry the mechanics. Everything below is context those files do
*not* capture.

## Current state

One thing *is* pending: the `eventkeys.py` refactor below is built, tested,
and gated, but **not committed or released**. Everything else is shipped.

| Item | State |
|---|---|
| Skill + docs + scripts | complete, v1.8.2, 9 portability checks passing |
| Test suite | 135 tests, four scripts, gates releases |
| Shared key vocabulary (`scripts/eventkeys.py`) | built + all gates green, **unreleased** — see *Architecture note* |
| `options.excludeAuthors` | v1.7.0; plan path live-validated on a throwaway board |
| Author resolution + no assignment | v1.8.0; full chain live-validated 2026-07-27 |
| Close / merge feed entries | v1.8.1; 14 missing entries backfilled to the live board |
| Live backfill | complete: 27 items, 80 feed entries |
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

**Tests named `test_regression_*` each encode a bug that reached a live board**
(or, for the 1.8.2 pair, a near-miss caught mid-run before it wrote).
All of them were mutation-tested — the fix was reverted and the test confirmed to
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
8. **The issues endpoint alone carries everything a close/merge entry needs**:
   `closed_at`, `closed_by` (the *merger* on a merged PR), and `merged_at`
   nested inside `pull_request`. No `pulls/N` call, no timeline walk. This is
   why the 1.8.1 fix costs zero extra requests.

## Architecture note — `scripts/eventkeys.py` is the key vocabulary

Added after 1.8.2. **Read this before touching anything that produces or
consumes an event key.**

An event key (`comment:445566`, `state:merged@<iso>`, `opened@<iso>`) is the
idempotency handle for one Updates-feed entry. Two components must agree on it:
`reconcile.py` decides an entry is new by testing the key against
`syncedEvents`, and `render-entries.py` stamps the key on what it posts.
Disagreement means duplicated or silently-dropped entries.

They disagreed twice — 1.8.1 and 1.8.2 were the same defect at two layers, both
caused by two implementations of one vocabulary. Each was patched with a test
comparing the two derivations. `eventkeys.py` removes the need for the
comparison: there is now **one** `key_for()`, and both scripts import it.

Three things that are not obvious:

1. **The import works because the scripts are run directly.** Python puts a
   script's own directory on `sys.path`, so `from eventkeys import key_for`
   resolves to the sibling file with no package, no install, and no
   `__init__.py`. This preserves the "clone it and it runs" property. It is
   also why `eventkeys.py` has no hyphen — it must be a valid module name,
   unlike `render-entries.py`, which is only ever executed.
2. **Tests must inject that path themselves.** `tests/helpers.py` loads the
   hyphenated scripts via `spec_from_file_location`, which does *not* put
   `scripts/` on `sys.path`. It inserts it explicitly. Remove that and every
   script fails to import under test for a reason that says nothing about the
   code.
3. **`test_both_scripts_share_one_implementation` asserts object identity**
   (`render.key_for is eventkeys.key_for`), not equal output. Mutation-tested
   with a *behaviourally identical* local copy — same logic, same results — and
   it still fails. The test forbids duplicating the logic, which is the actual
   failure mode; a test comparing outputs would have passed on that copy.

Adding an event kind means adding it to `ID_KEYED` or the timestamp branch in
`eventkeys.py`, never re-deriving a key at a call site.

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
- **The Author column names a person, never a bot** (changed in 1.8.0; before
  that the `[bot]` suffix was merely stripped, shipping `dependabot` as an
  author). `resolve-authors.py` walks GitHub for a human — opener, merger,
  auto-merge enabler, approver — and `automationAuthor` is the last resort.
  Unattributable raises rather than falling back to the bot login. Rationale
  from the user: everyone works through harnesses now, so "was it a bot" is not
  the interesting question; "whose account owns this" is. Bot-ness stays
  discoverable via real GitHub labels, which the skill does not invent.
- **No bot labelling** still holds for *formatting*: no badge, glyph, suffix, or
  separate group, and no formatting branches on bot-ness. Once attribution is
  resolved, an entry that came via automation renders identically to one that
  did not — `test_no_bot_marking_in_output` asserts exactly that.
- **The skill assigns nobody.** No monday people column is ever written. A
  GitHub issue has no opinion about who should own the row, and guessing puts
  work in somebody's "My Work" queue. `assignTo` was removed in 1.8.0.
- **`excludeAuthors` is item-scoped, and that is deliberate.** It filters which
  issues and PRs become board items; it does **not** filter feed entries. An
  excluded author commenting on a mirrored item is part of that conversation,
  and dropping the comment would strip context from an item the filter never
  named. Three more decisions worth not re-litigating: rows already on the
  board are named and frozen, never removed (deletion policy); excluded items
  are not adopted into state, because adoption claims a row as managed; and
  matching folds case *and* the `[bot]` suffix, so a user typing what they see
  on GitHub gets the filter they expected instead of a silent no-op. The
  un-exclude/backfill trap is documented in `references/state-file.md`.
- **Portability is enforced.** No GitHub/monday account, org, repo, board,
  column, or user id hardcoded. `./packaging/verify-portable.sh` has 9 checks,
  each negative-tested. The 9th is self-configuring: it reads the local
  `.monday-sync/*.json` and fails if any literal value from it — login, board
  name, repo slug, column id — appears in the shipped surface. It is the only
  check that can catch a hardcoded GitHub *login*, since a login looks like any
  other word. A clean checkout has nothing to compare against and says so. Upstream slug allowed only in README/CLAUDE/INSTALL and
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
- **Two correct, well-tested modules can still be broken at the seam.** The
  1.8.1 defect: `reconcile.py` built event keys from `opened@` + comments only,
  while `render-entries.py` had rendered `state:closed@` / `state:merged@` all
  along, and `state-file.md` documented the keys. Every unit was right; nothing
  connected them, so closing an issue quietly updated its columns and posted
  nothing. It survived a 110-test suite because `grep state:closed` hit exactly
  one file — the renderer's own tests. Found only by reading a live plan and
  asking why a PR that had just been merged reported `newEvents: 0`. **When two
  modules must agree on a value, assert the agreement in a test** — the fix adds
  `test_regression_state_event_key_matches_what_the_renderer_emits`, which
  compares the two implementations directly rather than each against a literal.
  Worth auditing the other shared vocabulary the same way (`comment:`,
  `review:`, `rcomment:`), which nothing currently cross-checks.
- **The seam bug had a twin one layer down, and it was found by luck.** While
  applying the 1.8.1 sync, an `events.json` built by hand omitted `id` on the
  comment events. `event_key()` fell through to `state:comment@<at>`, which
  matched nothing in `syncedEvents`, so 24 already-posted comments queued for a
  second posting — 39 entries where reconcile said 15. It was caught *only*
  because reconcile independently computed a count and the two disagreed.
  Nothing asserted the agreement. Two fixes in 1.8.2: `event_key()` now raises
  `MalformedEvent` instead of guessing, and `reconcile.comment_key()` exists so
  the two derivations can be compared in a test rather than each checked
  against a literal. **A cross-check you happen to notice is not a test.**
- **A silent omission looks exactly like "nothing happened."** Nobody noticed
  for three days because a board with correct State columns and no closure entry
  is indistinguishable from a board that is simply up to date. Bugs that *add*
  something wrong get reported; bugs that *skip* something do not.
- **Cost shape:** building and testing dominated; a real sync is ~90 API
  calls. Feed-entry work is the expensive part because each ~1.4 KB body
  round-trips through the model's context twice.

## Likely next steps (none blocking)

- Exercise **Step 1 (MCP absent)** and the **new-board offer** against a live
  session — reasoned but untested.
- Recurring sync via the `schedule` skill (`options.autoApprove: true` skips the
  plan confirmation and the Step 0 update check).
- **`syncLabelEvents` would close the last gap in the feed.** 1.8.1 covers
  close and merge, which are derivable from the issues endpoint. `reopened` is
  deliberately *not* emitted: a reopened item returns `closed_at: null` and the
  endpoint carries no timestamp for the transition, so there is nothing to key
  on without the per-item timeline. `state_events()` in `reconcile.py` is where
  that would go.
- `syncCommits` and `syncLabelEvents` are off by default and unexercised.

### The one loose thread the refactor left

`eventkeys.ID_KEYED` defines `review`, `rcomment`, and `commit` prefixes, and
`render-entries.py` can render all three. **`reconcile.py` derives none of
them** — it buckets comments only (`comment_key`) plus `opened@` and
`state_events()`. Nothing is broken today, because no code path fetches reviews
or commits, so there is no key to disagree about.

But that is exactly the shape 1.8.1 had: a renderer that handles a kind, a
reconciler that ignores it, and no failing test. **The moment review or commit
syncing is switched on, a plan that says "0 new events" for a PR with three
approvals is the same bug a third time.** The difference now is that the fix is
mechanical — derive via `key_for("review_approved", gid=...)` and it cannot
drift — and `test_reconcile_derivations_agree_with_the_shared_derivation` is
the place to extend.
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
