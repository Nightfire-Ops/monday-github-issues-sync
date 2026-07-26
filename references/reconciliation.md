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

Every rendered entry embeds its key as an HTML comment:

```html
<div><!-- gh-event:comment:445566 -->
<b>[2026-07-20 14:32 UTC] 💬 Comment — someone</b><br/>
```

The marker is invisible in the monday UI and makes the feed self-describing:
the posted history itself records what has been synced, so `syncedEvents` can
be rebuilt by reading updates back and extracting markers.

```
posted = set()
for update in item.updates:                      # newest-first from the API
    if m := re.search(r"<!-- gh-event:(.+?) -->", update.body):
        posted.add(m.group(1))
new_events = [e for e in events if e.key not in posted | state.syncedEvents]
```

**Markers only exist on entries posted after this mechanism shipped.** For an
item synced by an older version, or adopted with no state, the marker set is
empty and re-posting would duplicate the feed. Two safe options, in order:

1. **Trust state if present.** An adopted item with state keeps its history.
2. **Watermark instead of replay.** For an adopted item with no state and no
   markers, do *not* backfill. Set `lastEventAt` to now, post only events newer
   than that, and record `adoptedAt` on the item. The feed is missing history
   before adoption — say so in the run summary rather than risking a duplicate
   of every comment.

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
