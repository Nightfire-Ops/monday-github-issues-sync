# Install: monday-github-issues-sync

A Claude Code skill that mirrors a GitHub repository's issues and pull requests
into a monday.com board, so project management can see development activity
without living in GitHub.

**One-way: GitHub → monday.** Nothing is ever written back to GitHub.

## 1. Requirements

| Requirement | Check | Notes |
|---|---|---|
| Claude Code | `claude --version` | any recent version |
| `gh` CLI, authenticated | `gh auth status` | needs read access to the repo |
| `jq` | `jq --version` | 1.6+ |
| `python3` | `python3 --version` | 3.8+, for markdown → HTML conversion |
| monday MCP server | see below | needs write access to the target board |

No monday API token to manage — all writes go through the MCP server.

### Connecting the monday MCP server

If `/mcp` does not already list a monday server:

```bash
claude mcp add monday --transport http https://mcp.monday.com/mcp
```

Then run `/mcp` in Claude Code and authenticate in the browser. Confirm the
account you authenticate as can write to the board you intend to sync into.

## 2. Install the skill

Drop this folder into your skills directory.

**Personal** — available in every project:

```bash
cp -r monday-github-issues-sync ~/.claude/skills/
```

**Project** — available in one repository, and puts the sync state file next to
the code it describes:

```bash
mkdir -p .claude/skills
cp -r monday-github-issues-sync .claude/skills/
```

Verify it loaded — the skill is invoked as a slash command matching its
directory name, so it must stay named `monday-github-issues-sync`:

```
/monday-github-issues-sync
```

If the command does not appear, start a new Claude Code session.

You can also invoke it in plain language — "sync github issues to monday" —
which matches the skill's declared triggers.

## 3. First run

```
/monday-github-issues-sync
```

It asks for two things:

1. **GitHub repository** — `https://github.com/OWNER/REPO` or `OWNER/REPO`
2. **monday board** — a board URL, a numeric board id, or a board name

Then it verifies access, reports how many issues and PRs it found, provisions
14 columns and 2 groups on the board, shows a plan, and **waits for your
confirmation before writing anything.**

A first run on a large repo is capped (100 items, 1,500 feed entries) and will
stop cleanly and tell you what remains. Re-run to continue.

## 4. What lands on the board

One item per issue and per PR, in an `Issues` or `Pull Requests` group:

```
#123 Fix null deref in auth middleware
  GitHub URL          https://github.com/OWNER/REPO/issues/123
  Type                Issue
  GitHub State        Closed
  Author              someuser
  Labels              bug, p1
  Opened At           2026-07-01 14:32
  Last Activity       2026-07-20 09:15
  Closed / Merged At  2026-07-20 09:15
  Comment Count       12
```

Every comment, review, merge, and state change becomes a timestamped entry in
that item's Updates feed, oldest first.

Columns the skill does not own — including monday's default `Person`, `Status`,
and `Date` — are never touched. Add whatever you like alongside.

## 5. Read this before building dashboards

**monday's API cannot backdate an update.** Feed entries carry the time they
were *posted*, not the time the GitHub event happened. On a backfill that means
every entry is stamped with today's date.

Real GitHub time lives in two places, both authoritative:

- the bold `[YYYY-MM-DD HH:MM UTC]` prefix on every feed entry
- the item's `Opened At` / `Last Activity` / `Closed / Merged At` columns

**Build views, filters, and dashboards on the date columns.** A "development
activity over time" chart built on update timestamps shows one enormous spike
on the day you backfilled and nothing before it.

Note also that monday renders date columns in each account's local timezone,
while the stored values are UTC. A board on UTC-5 displays a 19:05 UTC event as
14:05. The stored data is correct; only the display shifts.

## 6. Sync state

State lives in `.monday-sync/<owner>-<repo>--board-<boardId>.json`.

**Commit it.** It maps GitHub numbers to monday item ids, and losing it means
the next run cannot tell what already exists and will duplicate the board.
`references/state-file.md` documents the schema and how to rebuild the mapping
from the board's `GitHub URL` column if the file is ever lost.

Tunable options live in that file under `options`:

| Option | Default | Effect |
|---|---|---|
| `assignTo` | `null` | assign every item to a monday user on create: `"me"` or a numeric user id |
| `automationAuthor` | `null` | attribute `[bot]`-authored events to this GitHub login instead |
| `syncCommits` | `false` | post each PR commit as a feed entry (noisy) |
| `syncLabelEvents` | `false` | post label/assignment changes (costs per-item API calls) |
| `maxItemsPerRun` | `100` | items created or updated per run |
| `maxEntriesPerItemBackfill` | `40` | feed entries per item on first sync |
| `maxEntriesPerRun` | `1500` | total feed entries per run |
| `autoApprove` | `false` | skip the plan confirmation — for scheduled runs only |

## 7. Updating

```bash
./scripts/update-skill.sh --check     # is a newer version available?
./scripts/update-skill.sh             # update in place
./scripts/update-skill.sh --version 1.2.0
```

The updater replaces the skill surface only — `SKILL.md`, `references/`,
`scripts/`, `packaging/`, `README.md`, `CLAUDE.md`, `VERSION`. Your
`.monday-sync/` state, which holds the item mapping that prevents duplicate
board rows, is never touched.

Point it at a fork with `MONDAY_SYNC_UPSTREAM=owner/repo`.

## 8. Recurring sync

After a successful run, ask for recurring sync and the skill will set it up via
the `schedule` skill. Unattended runs need `autoApprove: true` in the state
file; set that deliberately, since it removes the confirmation step.

## 9. Attribution

Entries are attributed to the GitHub login that submitted them, taken from the
event itself. A trailing `[bot]` suffix is stripped for display
(`dependabot[bot]` → `dependabot`); nothing is labelled or grouped as
automated, and formatting never branches on whether an author is a service.
Automated contributions are attributed exactly like any other.

To attribute automated activity to the person accountable for the repository
instead of the service that opened it, set `automationAuthor` to a GitHub login
in the state file. That is an ownership view — the named person did not write
the change — so set it deliberately.

## 10. Modifying and re-sharing

No GitHub account, org, repo, monday account, board id, or workspace may be
hardcoded in these files — all of them are runtime inputs. Before sharing a
modified copy:

```bash
./packaging/verify-portable.sh
```

It fails on emails, account subdomains, real board/item ids, generated column
ids, concrete repo slugs, and any bot-labelling logic. Exit code 0 means the
copy is safe to share.

## 11. Layout

```
SKILL.md                        the skill — 7 steps
README.md                       overview and known limits
references/board-schema.md      columns, types, columnValues payloads
references/github-queries.md    gh commands for backfill and incremental
references/reconciliation.md    idempotent re-run pattern
references/state-file.md        state schema, event keys, recovery
references/update-format.md     feed entry HTML, event glyphs, attribution
scripts/reconcile.py            board reconciliation + sync plan
scripts/render-entries.py       markdown → monday-HTML renderer
packaging/verify-portable.sh    portability lint
INSTALL.md                      this file
```
