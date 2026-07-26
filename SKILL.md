---
name: monday-github-issues-sync
version: 1.4.1
description: One-way sync of a GitHub repository's issues and pull requests into a monday.com board, preserving GitHub timestamps, so project management can see everything happening in development. Prompts for the repo URL and target board, backfills full history on first run, then syncs incrementally.
allowed-tools:
  - AskUserQuestion
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - mcp__monday__get_user_context
  - mcp__monday__create_board
  - mcp__monday__get_board_info
  - mcp__monday__get_board_items_page
  - mcp__monday__get_column_type_info
  - mcp__monday__create_column
  - mcp__monday__create_group
  - mcp__monday__create_item
  - mcp__monday__create_items
  - mcp__monday__change_item_column_values
  - mcp__monday__update_items
  - mcp__monday__create_update
  - mcp__monday__search
  - mcp__monday__list_workspaces
triggers:
  - sync github issues to monday
  - sync repo into monday board
  - mirror github activity into project management
  - update monday from github
---

## When to invoke this skill

Use this when someone wants GitHub development activity visible inside
monday.com: every issue and pull request as a board item, and every comment,
review, state change, label change, and merge as a timestamped entry in that
item's Updates feed. Runs on demand or on a schedule. Safe to re-run — it is
incremental and idempotent after the first backfill.

**Direction is one-way: GitHub → monday.** This skill never writes to GitHub.
Anything a human edits on the monday board (notes, custom columns, assignees)
is preserved; only the columns this skill owns get overwritten.

## Hard constraints — read before designing anything on top of this

1. **monday cannot backdate an update.** `create_update` stamps `created_at` as
   now. GitHub time is therefore carried as (a) date columns on the item and
   (b) a `[YYYY-MM-DD HH:MM UTC]` prefix inside each update body. Events are
   posted oldest-first so the feed reads chronologically.
2. **Volume is the main risk.** A repo with 400 issues and 20 events each is
   8,000 writes. The skill caps work per run and resumes from state — see
   *Step 7*. Never launch an uncapped backfill on a large repo without saying
   what it will cost.
3. **Writing to a shared board is outward-facing.** Always show the plan and
   get confirmation before the first write of a run, unless the user has
   already said to apply without asking (or this is a scheduled/unattended
   run configured with `autoApprove: true` in state).
4. **This skill is portable — keep it that way.** No GitHub account, org,
   repository, monday account, board id, or workspace may ever be hardcoded in
   these files. Every one of those is a runtime input from Step 1 or a value
   read back from the board. Attribution always comes from the GitHub event's
   own `user.login`, never from the account running the sync. Before sharing a
   modified copy, re-run the identity scan in `packaging/verify-portable.sh`.

## Step 0 — Check for updates

Run this **first, before collecting inputs**, so a fix ships before it is
needed rather than after a bad run:

```bash
scripts/update-skill.sh --check
```

`--check` always exits 0 and prints exactly one line to stdout. Human narration
goes to stderr — read stdout, ignore the exit code:

| stdout | Meaning | Do |
|---|---|---|
| `status=current installed=X upstream=X` | nothing to do | continue to Step 1 |
| `status=update-available installed=X upstream=Y` | newer version exists | ask (below) |
| `status=unavailable installed=X reason=<token>` | cannot tell — offline, `gh` unauthenticated, no access | continue to Step 1, say nothing |

`unavailable` is deliberately indistinguishable from `current` in effect. An
update check must never block the work it precedes, so a failed check is
silent — do not report it, do not retry, do not ask the user to fix `gh`.

On `update-available`, ask once:

> A newer version of this skill is available (1.1.0 → 1.2.0). Update before
> running the sync?

On yes: run `scripts/update-skill.sh` (this one *does* exit non-zero on real
failure — report that), then **re-read `SKILL.md` from disk**, because the steps
below may have changed under you, and start again from Step 1.
On no: continue with the installed version and do not ask again this session.

Skip Step 0 entirely when `options.autoApprove` is set: an unattended run must
not stall on a prompt, and must not silently swap its own logic mid-flight.

Never update without asking. The user may be mid-task on a board where
behaviour changes matter.

## Step 1 — Verify the monday MCP server

**Before asking the user for anything.** There is no point collecting a repo
and a board if the writes cannot happen — and finding out halfway through a
backfill leaves a half-populated board.

Call `mcp__monday__get_user_context`. It is read-only, needs no arguments, and
returns the authenticated user and account.

- **Returns a user** → the server is connected and authenticated. Keep the
  numeric user id; Step 2 needs it for assignment.
- **Tool is not available** (no `mcp__monday__*` tools in this session) → the
  server is not installed. Stop and tell the user:

  > This skill needs the monday.com MCP server, which isn't connected. Install
  > it with:
  >
  > ```
  > claude mcp add monday --transport http https://mcp.monday.com/mcp
  > ```
  >
  > Then run `/mcp` to authenticate in the browser, restart the session, and
  > invoke this skill again.

  Do not attempt to install or authenticate it yourself — it needs an
  interactive browser login as the right monday account.
- **Tool exists but errors** (auth expired, no permission) → report the error
  verbatim and tell the user to re-run `/mcp`. Do not proceed.

Never fall back to guessing board structure or queuing writes for later. No
MCP, no run.

## Step 2 — Collect inputs

Ask for both inputs together with `AskUserQuestion` (or accept them if the user
already supplied them in the prompt):

- **GitHub repository** — a URL (`https://github.com/owner/repo`) or `owner/repo`.
  Normalize to `owner/repo`.
- **monday board** — accept any of: a board URL
  (`https://<account>.monday.com/boards/1234567890` → id is the trailing
  number), a numeric board id, or a board name. For a name, resolve it with
  `mcp__monday__search` (`searchType: "BOARD"`) and if more than one matches,
  list the candidates with their workspace and ask which one.

  **Recommend a new, empty board.** Say so when asking:

  > Which monday board should this sync into? A **new, empty board** is
  > recommended — this skill adds 14 columns and 2 groups, and on a busy
  > existing board that structure is intrusive and easy to confuse with
  > hand-managed work. I can create one for you.

  If they want one, use `mcp__monday__create_board` and confirm the workspace
  first. Syncing into an existing board is fully supported — reconciliation
  ignores rows without a `GitHub URL` — but a dedicated board is cleaner and
  makes the "everything here came from GitHub" guarantee obvious.

Then verify both before doing anything else:

```bash
gh auth status
gh repo view OWNER/REPO --json name,isPrivate,defaultBranchRef
```

**Do not use `gh repo view --json issues,pullRequests` to size the job.** Those
fields count only *open* items — on a repo with 6 open and 12 closed issues it
reports 6, understating the backfill by 3x. Count from the same endpoint the
sync itself reads:

```bash
gh api "repos/OWNER/REPO/issues?state=all&per_page=100" --paginate \
  --jq '[.[] | {pr: (.pull_request != null), state}]' \
  | jq -s 'add | {issues: map(select(.pr|not))|length,
                  prs: map(select(.pr))|length,
                  open: map(select(.state=="open"))|length,
                  closed: map(select(.state=="closed"))|length}'
```

Call `mcp__monday__get_board_info` on the resolved board id. If either check
fails, stop and report which one — do not partially proceed.

**Resolve the assignee now, once.** If `options.assignTo` is `"me"` (or this is
a first run and the user wants items owned on arrival), call
`get_user_context` and cache the numeric user id for the whole run. Assigning
on create is what stops the user having to walk the board afterwards. See
`references/board-schema.md`.

Report back the scale you are about to sync (open + closed issue count, PR
count) so the user can narrow scope before committing.

## Step 3 — Load state, then reconcile against the board

State lives at `.monday-sync/<owner>-<repo>--board-<boardId>.json` relative to
the current working directory. Read `references/state-file.md` for the schema
and **`references/reconciliation.md` for the pattern — it is what makes
re-running safe.**

State is a cache, not the truth. **The board is the truth.** Never decide what
to create from the state file alone: it goes stale when someone deletes an item
in monday, when a run dies mid-write, when two machines sync the same pair, or
when the file simply is not committed. Trusting it blindly duplicates the board.

So on **every** run, not just when state looks broken:

1. Page the board with `get_board_items_page`, including the `GitHub URL`
   column, and rebuild the identity map from what is actually there.
2. Repair state against it — adopt items present on the board but missing from
   state, drop items in state that no longer exist, report duplicates.
3. Only then diff.

```bash
scripts/reconcile.py OWNER/REPO \
  --board board_items.json --github issues.json \
  --comments comments.json --state .monday-sync/<file>.json
```

It emits the plan as JSON on stdout and the summary on stderr. Use its output
as Step 6's plan rather than recomputing by hand.

If the file exists but `boardId` inside it disagrees with the resolved board,
stop and ask — the board was changed or the file was copied.

## Step 4 — Provision the board schema (first run only)

Read `references/board-schema.md` for the full column list, types, and the
exact `columnValues` payload shape for each.

Procedure:

1. `get_board_info` to list existing columns and groups.
2. Match required columns to existing ones **by title, case-insensitively**.
   Reuse any that already exist with a compatible type.
3. Create only what is missing, via `create_column`. Record every returned
   column id into `columnMap` in the state file — the ids are generated by
   monday and are the only reliable handle afterward.
4. If `assignTo` is set, locate the people column — an existing `people`-type
   column titled `Person`, `Owner`, or `Assignee` — and record it in
   `columnMap.assignee`. Create `Owner` only if the board has no people column.
5. Ensure two groups exist: `Issues` and `Pull Requests` (`create_group`).
   Record their ids in `groupMap`. **Match groups by id, never by title** — a
   default monday board ships with two groups both titled `Group Title`, so
   title matching is ambiguous from the very first run.
6. Write the state file now, before any item writes. If the run dies
   mid-backfill, this is what prevents a duplicate schema on retry.

**Default board content.** A newly created monday board comes with placeholder
items (`Item 1`…`Item 5`) and default `Person` / `Status` / `Date` columns.
The placeholders have no `GitHub URL` value, so sync ignores them safely — but
they clutter the board and PMs read them as real rows. On a first run, if every
existing item lacks a `GitHub URL`, and the names match monday's placeholder
pattern, offer to archive them. Ask; never archive without confirmation.

The default `Status` and `Date` columns are deliberately *not* reused —
`Status` carries monday's own workflow labels (`Working on it` / `Done` /
`Stuck`), which mean something different from GitHub state. Mixing them
destroys the distinction. Leave them for humans.

The default `Person` column **is** reused when `assignTo` is set, because it is
the column monday's "My Work" and notifications read from. That is the whole
point of assigning on create.

Never delete or retype a column that already exists. If a required title
exists with an incompatible type (e.g. `Created At` is text, not date), create
a suffixed column (`Created At (GitHub)`) and note the substitution in the
run summary rather than mutating the user's board.

## Step 5 — Fetch from GitHub

Read `references/github-queries.md` for the exact commands. The shape:

- **First run:** list all issues and PRs, then sweep all comments and reviews
  repo-wide. Do *not* walk per-item timelines for a backfill — the repo-wide
  comment endpoints are an order of magnitude cheaper.
- **Incremental run:** one `since=<lastSyncedAt>` pass over each endpoint.
  GitHub's issues endpoint returns PRs too, so a single call covers both;
  distinguish them by the presence of a `pull_request` key.

Write raw fetch output to the scratchpad as JSON rather than holding it all in
context. Parse with `jq`. Set the new watermark to the run start time (captured
*before* fetching), not the finish time, so events landing mid-run are not
skipped on the next pass.

## Step 6 — Diff and build a plan

For each fetched issue/PR, decide against state:

| Condition | Action |
|---|---|
| Not in `itemMap` | **create** item + backfill its events |
| In `itemMap`, `updatedAt` newer than stored | **update** columns + append new events |
| In `itemMap`, unchanged | **skip** |
| In `itemMap` but 404 on GitHub (deleted/transferred) | **flag** in summary, leave the monday item alone |

An event is new if its event key is absent from that item's `syncedEvents`.
Event keys are stable GitHub ids (`comment:123456`, `review:789`,
`state:closed@<iso>`) — see `references/state-file.md`.

Present the plan as counts, not a wall of text:

```
Repo:  owner/repo → board 1234567890 ("Engineering")
Mode:  full backfill
Plan:  312 items to create (248 issues, 64 PRs)
       1,847 feed entries to post
       ~95 monday API calls (batched)
Cap:   this run will process 100 items; re-run to continue
```

**If any fetched author carries a `[bot]` suffix**, report the count alongside
the plan and offer the ownership override once, here:

> 7 of 8 PRs were opened by automation (`dependabot`). Attribute these to a
> specific GitHub login instead — e.g. whoever owns dependency upgrades — or
> keep the original submitter?

Record the answer as `options.automationAuthor` in state so it is not asked
again. Default to keeping the real submitter if the user does not care. Never
suggest a specific login; read it from the user.

Then confirm before writing.

## Step 7 — Apply writes

Order matters. For each item, create/update the item first, then post its feed
entries oldest-first.

**Batching — use it, this is where runs succeed or time out:**

- `create_items` — up to 20 items per call
- `update_items` — up to 40 column updates per call
- `create_update` — one call per feed entry, no batch API. This dominates the
  run. Cap it.

**Per-run caps** (defaults; raise only if the user asks):

- 100 items created or updated
- 40 feed entries per item on first backfill (post the newest 40 and note the
  truncation in the item's first update entry — do not silently drop history)
- 1,500 total feed entries

When a cap is hit: persist state, stop cleanly, and tell the user exactly what
remains and that re-running continues from there. A capped run is a success,
not a failure — but say so plainly rather than implying completeness.

**After every batch**, update the state file. Not at the end. A crash between
writes and state persistence is what creates duplicates.

Read `references/update-format.md` for the required HTML body format of feed
entries. monday updates take HTML, not markdown — GitHub comment bodies must
be converted, and long bodies truncated with a link through to GitHub.

**Use the shipped renderer rather than converting by hand:**

```bash
scripts/render-entries.py OWNER/REPO < events.json > bodies.json
```

It emits each event's `html` (the update body) and `key` (the idempotency key),
sorted oldest-first per item. Hand-rolling the conversion reliably re-breaks
heading and list handling and risks unescaped `<`/`&` from stack traces in
comment bodies. Post `bodies.json[].html` verbatim.

## Step 8 — Report

Summarize:

- items created / updated / skipped
- feed entries posted
- new watermark
- anything skipped, capped, truncated, or flagged, and the command to continue
- any board schema substitutions made in Step 3

Then, if this is a first run, offer to set up recurring sync via the `loop` or
`schedule` skill, and mention that `autoApprove: true` in the state file lets
unattended runs skip the Step 6 confirmation.

## Deletion policy — nothing is removed without asking

This skill **never deletes, archives, or clears anything on its own.** Not
items, not columns, not groups, not board content it did not create. Every
destructive action is proposed and waits for an explicit yes.

| Situation | What the skill does |
|---|---|
| Duplicate items found | names them, keeps the oldest, **asks** before touching the rest |
| Item 404s on GitHub (deleted or transferred) | flags it, **leaves the monday item alone** |
| monday placeholder rows (`Item 1`…`Item 5`) | **offers** to archive them; never archives unasked |
| Existing column with a conflicting type | creates a suffixed column instead of retyping |
| Rows with no `GitHub URL` | untouched — that is somebody else's work |
| Human comments in an item's Updates feed | never removed; the skill only appends |

A monday item can carry human discussion this skill did not write, so removing
one destroys work that exists nowhere else. Report and let a person decide.

### If a user reports that something was deleted

Take it seriously and be straightforward:

1. **Point them at their monday.com admin.** Deleted items go to monday's
   recycle bin rather than disappearing. Admins can see what was removed and
   restore it on request — this is recoverable, and they should ask rather than
   assume the data is gone.
2. **Do not attempt to re-create the item from GitHub as a "fix."** A restored
   item keeps its history and human comments; a re-synced one does not, and
   re-creating it first makes the restore land as a duplicate.
3. **Check the state file and the run summary** to establish what this skill
   actually wrote. Every run reports items created, updated, and skipped, and
   the skill has no code path that deletes.
4. If a deletion genuinely came from a run, that is a bug worth reporting —
   capture the state file and the summary.

## Failure handling

| Symptom | Cause | Response |
|---|---|---|
| `ColumnValueException` | label not on the board | retry that write with `createLabelsIfMissing: true` |
| monday 429 / rate limit | too many writes | back off, persist state, stop cleanly and report remaining work |
| `gh` 403 with rate limit body | GitHub API budget exhausted | report reset time from `gh api rate_limit`; do not spin |
| Item name > 255 chars | long issue title | truncate title, keep the `#123 ` prefix, full title goes in the item's first feed entry |
| Duplicate items appear | state file lost or not committed | do not auto-delete; report and offer a reconciliation pass matching on the GitHub URL column |

Never swallow a write failure. If a batch partially fails, record which
entries succeeded in state, then report the failures individually.
