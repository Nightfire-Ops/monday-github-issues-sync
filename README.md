# monday-github-issues-sync

A [Claude Code](https://claude.com/claude-code) skill that mirrors a GitHub
repository's issues and pull requests into a monday.com board, so project
management can see what development is actually doing without living in GitHub.

**One-way: GitHub → monday.** Nothing is ever written back to GitHub.

## What it does

- One monday item per issue and per pull request
- Columns carrying state, author, assignees, labels, milestone, branch, and
  real GitHub timestamps
- Every comment, review, merge, close, and reopen as a timestamped entry in
  that item's Updates feed, oldest first
- Items assigned to a monday user on creation, so nothing lands unowned

Full history on the first run, incremental after that. Every run reconciles
against the board before writing, so **re-running never duplicates**.

## Before you install: the monday MCP server

This skill talks to monday.com through the **monday MCP server**. Without it
the skill cannot read or write a board at all, so set it up *before* installing
the skill.

Check whether it is already connected — in Claude Code, run:

```
/mcp
```

If no monday server is listed, add it:

```bash
claude mcp add monday --transport http https://mcp.monday.com/mcp
```

Then run `/mcp` again and authenticate in the browser. **Sign in as an account
with write access to the board you intend to sync into** — a viewer account
authenticates fine and then fails on the first write.

The skill re-checks this itself at Step 1 of every run and stops with setup
instructions if the server is missing, so a bad install fails fast rather than
half-populating a board.

## Install

**One command:**

```bash
git clone https://github.com/Nightfire-Ops/monday-github-issues-sync \
  ~/.claude/skills/monday-github-issues-sync
```

That's it — restart Claude Code and run `/monday-github-issues-sync`. No
authentication, no `gh`, no download step. The directory name *is* the slash
command, so keep it as-is.

**Project-scoped instead** (keeps sync state beside the code it describes):

```bash
git clone https://github.com/Nightfire-Ops/monday-github-issues-sync \
  .claude/skills/monday-github-issues-sync
```

**Or let Claude do it** — paste this into Claude Code:

```
Install the Claude Code skill at
https://github.com/Nightfire-Ops/monday-github-issues-sync
```

Claude reads [CLAUDE.md](CLAUDE.md) in the repo, which tells it where to install,
what to verify, and what not to touch.

See [INSTALL.md](INSTALL.md) for requirements and configuration.

## Use

In Claude Code:

```
/monday-github-issues-sync
```

The skill is invoked as a slash command matching its directory name. What
happens, in order:

1. **Update check** — reports whether a newer version exists and asks whether
   to update before running. Declining is fine; a failed check never blocks.
2. **monday MCP check** — confirms the server is connected and authenticated.
   If not, it stops and tells you how to add it.
3. **Asks for the GitHub repository** — a URL
   (`https://github.com/OWNER/REPO`) or `OWNER/REPO`. This is the repo whose
   issues and pull requests get mirrored. Read-only; nothing is ever written
   back to GitHub.
4. **Asks for the monday board** — a board URL
   (`https://<account>.monday.com/boards/1234567890`), a board id, or a board
   name. **A new, empty board is recommended** — the skill adds 14 columns and
   2 groups, which is intrusive on a busy existing board and easy to confuse
   with hand-managed work. It will offer to create one for you.
5. **Reports the scale** — how many issues and PRs it found, open and closed.
6. **Shows a plan and waits for your confirmation** before the first write.

Syncing into an existing board works too: reconciliation ignores any row
without a `GitHub URL`, so hand-created items are never touched.

You can also invoke it in plain language — "sync github issues to monday",
"mirror our repo into the board" — which matches the skill's triggers.

### Who the Author column names

Always a person, never a bot. Work pushed through a harness is already authored
by your own GitHub account — the tool shows up as a `Co-Authored-By` trailer,
not as the author — so this needs no configuration in the usual case.

Genuine third-party apps like dependabot are different: they open items under
their own identity. For those the sync asks GitHub who actually touched the
item — who merged it, who enabled auto-merge, who approved it — and only if
nobody has does it fall back to `options.automationAuthor`, the login you
nominate as accountable for automation.

You can still find every bump: GitHub's own labels (`dependencies`,
`github_actions`) ride along in the `Labels` column, so the board stays
searchable without a bot's name sitting in an authorship field.

Rows arrive **unassigned**. The skill never writes to a monday people column —
a GitHub issue has no opinion about who should own the row.

### Keeping automation off the board

Dependency-bump PRs can outnumber human work several to one and bury it. When
the sync sees automation authors it offers three choices, once, before the
first write: keep them as they are, attribute them to a GitHub login who owns
that work, or leave their items off the board entirely.

The last one is `options.excludeAuthors` in the state file — a list of logins,
matched case-insensitively with the `[bot]` suffix optional, so you can type
the name you see on GitHub:

```json
"options": { "excludeAuthors": ["some-bumper"] }
```

It filters which issues and PRs become board items. It does not filter comments
— an excluded author replying on somebody else's issue still shows up there,
because that is part of the conversation.

Adding a login later does **not** remove rows it already created. Those are
named in the run summary and stop updating; taking them off the board is your
call, and the skill will ask before doing anything. See
`references/state-file.md`.

## Update

The skill checks for updates when invoked and asks before applying one. You can
also drive it directly:

```bash
./scripts/update-skill.sh --check     # prints one status line, always exits 0
./scripts/update-skill.sh             # update in place
```

`--check` is safe to script: it always exits 0 and prints exactly one line to
stdout — `status=current`, `status=update-available`, or `status=unavailable`
with a reason — so "cannot reach the upstream" is handled the same as "nothing
to do" without special-casing exit codes. Applying an update still exits
non-zero on real failure.

Updates come from this repository over plain HTTPS — no auth and no `gh`
needed. Override for a fork with `MONDAY_SYNC_UPSTREAM=owner/repo`; private
forks fall back to `gh` automatically if it is installed and authenticated.

The updater replaces the skill surface only. Your `.monday-sync/` state — the
item mapping that prevents duplicates — is never touched.

Point it at a different fork with `MONDAY_SYNC_UPSTREAM=owner/repo`.

## Tests

```bash
python3 -m unittest discover -s tests    # no dependencies
PYTHONPATH=tests pytest tests/           # if you prefer pytest
```

75 tests, 99% statement coverage of both scripts. Stdlib `unittest` on purpose —
cloning the skill and verifying it should not require installing anything.

Tests named `test_regression_*` each encode a bug that reached a live monday
board: the doubled footer link, cross-repo `#NNN` linkification inside quoted
upstream changelogs, nested anchors, unescaped HTML in comment bodies, and
state-loss duplicating the board. Every one was verified to fail when its fix is
reverted, so they are regression tests in fact and not just in name.

`packaging/release.sh` runs the suite before building; a failure blocks the
release.

## Releasing

Maintainers only:

```bash
./packaging/release.sh 1.2.0            # bump, rebuild dist/, versioned zip
./packaging/release.sh 1.2.0 --publish  # + tag, push, GitHub release
```

Every release rebuilds `dist/` and produces both `<name>-<version>.zip` and a
`<name>.zip` "latest" artifact. The release refuses to proceed if
`packaging/verify-portable.sh` fails.

## Portability

No GitHub account, org, repository, monday account, board id, or column id is
hardcoded anywhere — all are runtime inputs. Enforced by:

```bash
./packaging/verify-portable.sh
```

Six checks covering emails, account subdomains, real ids, generated column ids,
concrete repo slugs, and attribution logic. Run before sharing a fork.

## Deletion and recovery

**This skill never deletes, archives, or clears anything without asking.** It
creates items, updates the columns it owns, and appends to Updates feeds.
Duplicates, stale rows, and monday's default placeholder items are all
*reported* — removal is always proposed and waits for an explicit yes. Rows
without a `GitHub URL` are ignored entirely; columns it does not own are never
written to; human comments in a feed are never removed.

**If you believe something was deleted:** contact your monday.com administrator
before assuming the data is gone. Deleted items go to monday's recycle bin
rather than vanishing — admins can see what was removed and restore it on
request. Do not re-run the sync to "rebuild" the item first: a restored item
keeps its full history and human comments, while a re-synced one does not, and
re-creating it makes the restore land as a duplicate.

## Known limits

- **monday cannot backdate updates** — the API's `original_creation_date`
  argument is accepted and silently ignored (tested). Entries are stamped with
  the time they were posted, not when the GitHub event happened. Real GitHub time is in
  the bold prefix of every entry and in the item's date columns — build views
  and dashboards on the date columns, never on update timestamps.
- **Commit-level and label-change history are off by default** — noisy, and
  they cost extra API calls. Enable in `options`.
- **Per-run caps** (100 items, 1,500 feed entries) stop a large backfill from
  running away. A capped run stops cleanly and reports what remains.
- **Comment edits are not re-synced.** Comment ids are stable across edits; an
  edit is not a new event.

## Layout

```
CLAUDE.md                       install instructions Claude follows
handoff.md                      development context for contributors
SKILL.md                        the skill — 7 steps
INSTALL.md                      requirements, setup, configuration
references/board-schema.md      columns, types, columnValues payloads
references/github-queries.md    gh commands for backfill and incremental
references/reconciliation.md    the idempotent re-run pattern
references/state-file.md        state schema, event keys, recovery
references/update-format.md     feed entry HTML, glyphs, attribution
scripts/reconcile.py            board reconciliation + sync plan
scripts/render-entries.py       markdown → monday-HTML renderer
scripts/resolve-authors.py      resolves the human behind each item
tests/                          unittest suite (99% coverage)
scripts/update-skill.sh         in-place updater
packaging/release.sh            version bump + dist + zip + publish
packaging/verify-portable.sh    portability lint
```

## License

MIT
