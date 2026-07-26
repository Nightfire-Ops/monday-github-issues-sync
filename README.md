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

## Install

**Paste this into Claude Code:**

```
Install the Claude Code skill from https://github.com/Nightfire-Ops/monday-github-issues-sync
It is a PRIVATE repo — fetch it with `gh repo clone` (not WebFetch), then follow
the CLAUDE.md at its root.
```

The private-repo note matters: `raw.githubusercontent.com` and the repo page
both return **404** to unauthenticated requests, so an agent that reaches for a
plain HTTP fetch sees nothing and cannot discover `CLAUDE.md` on its own. Once
cloned with `gh`, [CLAUDE.md](CLAUDE.md) tells Claude exactly where to install,
what to check, and what not to touch.

If the repo is ever made public, the URL alone is enough and the note can go.

**Manually:**

```bash
gh repo clone Nightfire-Ops/monday-github-issues-sync
cp -r monday-github-issues-sync ~/.claude/skills/
```

Or scope it to one project by copying into that repo's `.claude/skills/`.

See [INSTALL.md](INSTALL.md) for requirements, monday MCP setup, and
configuration.

## Use

In Claude Code:

```
/monday-github-issues-sync
```

The skill is invoked as a slash command matching its directory name. It will
ask for two things:

1. **GitHub repository** — `https://github.com/OWNER/REPO` or `OWNER/REPO`
2. **monday board** — a board URL, a numeric board id, or a board name

Then it verifies access, reports how many issues and PRs it found, provisions
the board, shows a plan, and waits for confirmation before writing anything.

You can also invoke it in plain language — "sync github issues to monday",
"mirror our repo into the board" — which matches the skill's triggers.

## Update

```bash
./scripts/update-skill.sh --check     # is there a newer version?
./scripts/update-skill.sh             # update in place
```

The updater replaces the skill surface only. Your `.monday-sync/` state — the
item mapping that prevents duplicates — is never touched.

Point it at a different fork with `MONDAY_SYNC_UPSTREAM=owner/repo`.

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

## Known limits

- **monday cannot backdate updates.** Feed entries are stamped with the time
  they were posted, not when the GitHub event happened. Real GitHub time is in
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
SKILL.md                        the skill — 7 steps
INSTALL.md                      requirements, setup, configuration
references/board-schema.md      columns, types, columnValues payloads
references/github-queries.md    gh commands for backfill and incremental
references/reconciliation.md    the idempotent re-run pattern
references/state-file.md        state schema, event keys, recovery
references/update-format.md     feed entry HTML, glyphs, attribution
scripts/reconcile.py            board reconciliation + sync plan
scripts/render-entries.py       markdown → monday-HTML renderer
scripts/update-skill.sh         in-place updater
packaging/release.sh            version bump + dist + zip + publish
packaging/verify-portable.sh    portability lint
```

## License

MIT
