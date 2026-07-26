# Reconciliation — how the sync stays idempotent

The sync is not "fetch GitHub, write monday." It is **reconcile → diff → apply**.
Every run reconstructs what is already on the board before deciding to write
anything, so re-running is always safe and never duplicates.

Run this on **every** run, not only when state looks broken.

## Why state alone is not enough

The state file is fast but not authoritative. It goes stale whenever:

- someone deletes or archives an item in the monday UI
- a run dies between writing to monday and persisting state
- two machines (or a laptop and CI) sync the same pair
- the file is lost, not committed, or restored from an older commit
- the board is restored from a monday backup

Trusting it blindly produces duplicates in the first case and phantom skips in
the second. **The board is the source of truth for what exists; state is a
cache that makes the run cheap.**

## Three layers of identity

Each layer is a fallback for the one above. A sync is idempotent if *any* of
them survives.

| Layer | Where | Survives | Cost |
|---|---|---|---|
| 1. `itemMap` in state | `.monday-sync/*.json` | nothing (a plain file) | free |
| 2. `GitHub URL` column | on every item | state loss, machine change, backup restore | one paginated board read |
| 3. `#<number>` name prefix | item name | someone clearing the URL column | same read |

Layer 2 is the workhorse. The URL is exact, machine-parseable, and unique per
issue/PR, which is why the column is mandatory and why nothing should ever
write to it by hand.

## Phase 1 — Reconcile

Read every item on the board with its `GitHub URL` column, then rebuild the
mapping from what is actually there:

```
observed = {}                       # "issue/123" -> mondayItemId
for item in board_items:
    key = parse_key(item.github_url)          # owner/repo + number + type
    if key is None:
        continue                              # human-created row; leave alone
    if key in observed:
        record_duplicate(key, item)           # report, never auto-delete
    else:
        observed[key] = item.id
```

Only items whose URL matches **this run's repo** participate. A board can host
several repos; parse the owner/repo out of the URL and ignore the rest.

Then diff `observed` against `state.itemMap` and repair state to match the
board:

| Situation | Meaning | Action |
|---|---|---|
| in both, same id | normal | keep |
| in board, not in state | state lost or another run created it | **adopt** into state; do not create |
| in state, not on board | item deleted in monday | drop from state; recreate as new |
| in both, different id | duplicate created earlier | keep oldest, report the other |

Adoption is what makes a lost state file a non-event. An adopted item has no
`syncedEvents` history — see *Feed reconciliation* below for what that costs.

## Phase 2 — Diff

Decide per item, and **per field**. Do not rewrite all 14 columns because one
changed; that floods the monday activity log and makes real edits invisible.

```
if key not in observed:          -> CREATE item, then backfill events
elif gh.updated_at > state.updatedAt:
     changed = fields_that_differ(gh, board_item)
     if changed: -> UPDATE only those columns
     new_events = [e for e in events if e.key not in state.syncedEvents]
     if new_events: -> POST those events only
else:                            -> SKIP entirely
```

When comparing dates, read the column's **`value`** (raw UTC JSON), never
`text` (rendered in account-local time). Comparing `text` mismatches on every
run for any account not on UTC, which turns every incremental sync into a full
rewrite. See `board-schema.md`.

`updated_at` is a cheap gate, not a decision: GitHub bumps it for events this
skill does not sync (reactions, projects, subscriptions). Always confirm with a
field-level diff before writing.

## Phase 3 — Apply

Ordered, capped, and state-persisted after every batch. See `SKILL.md` Step 6.

## Feed reconciliation

Items dedupe on identity; feed entries dedupe on **event key**
(`comment:445566`, `review:778899`, `opened@<iso>` — see `state-file.md`).

**monday strips HTML comments from update bodies.** An earlier design embedded
`<!-- gh-event:comment:445566 -->` in each entry to make the feed
self-describing; reading posted updates back proved the sanitiser removes it,
along with rewriting `<br/>` to `<br>` and adding `target`/`rel` to anchors.
Do not rely on injected markup surviving.

What *does* survive is the **footer link's href**, which every entry carries and
which already contains the GitHub identifier:

```
.../issues/123#issuecomment-445566   ->  comment:445566
.../pull/45                         ->  opened (no comment fragment)
```

So a feed can still be reconciled without the state file, by parsing hrefs out
of the posted updates:

```
posted = set()
for update in item.updates:
    for m in re.finditer(r"#issuecomment-(\d+)", update.body):
        posted.add(f"comment:{m.group(1)}")
new_events = [e for e in events if e.key not in posted | state.syncedEvents]
```

This recovers comment and review identity exactly. It cannot distinguish an
`opened` entry from any other entry lacking a fragment, so treat "an update
exists whose href is the bare issue/PR URL" as evidence the opened entry was
posted.

For an item adopted with no state at all, prefer the watermark path over
replay: set `lastEventAt` to now, post only newer events, record `adoptedAt`,
and say in the run summary that pre-adoption history is missing. Losing history
is recoverable by a human reading GitHub; a duplicated feed is not.

Never resolve this by matching on body text. Comments get edited, and a
near-match is not an identity.

## Reporting

A reconciliation that silently repairs things is indistinguishable from one
that silently breaks them. Every run reports:

```
Reconciled 26 board items against 26 GitHub items
  adopted        2   (on board, missing from state)
  dropped        0   (in state, no longer on board)
  duplicates     0
  skipped       23   (unchanged since last sync)
  to update      1   (2 columns, 1 new comment)
  to create      0
```

Duplicates and adoptions are always named individually, not just counted.

## What is never done automatically

- **Deleting or archiving a monday item.** Items carry human comments this
  skill did not write. Report and let a person decide.
- **Touching an item with no `GitHub URL`.** That is somebody's own row.
- **Writing to columns outside `columnMap`.** Humans own the rest of the board.
- **Re-posting an edited comment.** Comment ids are stable across edits; an
  edit is not a new event.
