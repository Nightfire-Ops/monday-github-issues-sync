# Board schema

Columns this skill owns. Match by title case-insensitively against existing
board columns before creating anything; reuse compatible matches.

Any column not in this list is left completely alone — humans can add whatever
they want to the board and this skill will not touch it.

## Required columns

| Title | Type | Holds | Owned |
|---|---|---|---|
| `GitHub URL` | `link` | canonical issue/PR URL — the reconciliation key | yes |
| `Type` | `status` | `Issue` / `Pull Request` | yes |
| `GitHub State` | `status` | `Open` / `Closed` / `Merged` / `Draft` | yes |
| `Author` | `text` | GitHub login of the opener, `[bot]` suffix stripped | yes |
| `GitHub Assignees` | `text` | comma-separated GitHub logins, same normalization | yes |
| `Labels` | `dropdown` (multi) | GitHub labels | yes |
| `Milestone` | `text` | milestone title, empty if none | yes |
| `Opened At` | `date` (with time) | GitHub `created_at` | yes |
| `Last Activity` | `date` (with time) | GitHub `updated_at` | yes |
| `Closed / Merged At` | `date` (with time) | `merged_at` if merged, else `closed_at` | yes |
| `Comment Count` | `numbers` | total comments + reviews | yes |
| `Branch` | `text` | PR head → base, empty for issues | yes |
| `Linked` | `text` | `#12, #34` — linked issues for a PR, linked PRs for an issue | yes |
| `Last Synced` | `date` (with time) | when this skill last wrote the item | yes |

`Type` and `GitHub State` are separate on purpose: a merged PR and a closed
issue are not the same signal to a PM, and collapsing them loses the
distinction between "closed as completed" and "merged".

## Groups

- `Issues`
- `Pull Requests`

Created if absent. Items go in the group matching their type. State is carried
by the `GitHub State` column, not by group membership, so PMs can regroup the
board however they like without breaking sync.

## Item name format

```
#123 Fix null deref in auth middleware
```

The `#<number>` prefix is a human-readable fallback identity if the state file
is ever lost. Truncate the title so the whole name stays under 255 chars,
ending with `…`; the untruncated title goes in the item's first feed entry.

## columnValues payloads

`create_item` / `create_items` / `update_items` all take `columnValues` as a
**JSON string**, keyed by the column ids recorded in `columnMap` — never by
title.

**Generated ids do not match the type name.** `create_column` returns an id
whose prefix is often *not* the `columnType` you asked for — verified on a real
board:

| Requested type | Returned id prefix |
|---|---|
| `status` | `color_<suffix>` |
| `numbers` | `numeric_<suffix>` |
| `dropdown` | `dropdown_<suffix>` |
| `link` / `text` / `date` | `link_…` / `text_…` / `date_…` |

Never construct or guess a column id from its type. Capture the `column_id`
from each `create_column` response into `columnMap` and use only that.

```json
{
  "<link_col>":      { "url": "https://github.com/o/r/issues/123", "text": "#123" },
  "<type_col>":      { "label": "Issue" },
  "<state_col>":     { "label": "Open" },
  "<author_col>":    "alice",
  "<assignees_col>": "bob, carol",
  "<labels_col>":    { "labels": ["bug", "p1"] },
  "<milestone_col>": "v2.0",
  "<opened_col>":    { "date": "2026-07-01", "time": "14:32:00" },
  "<activity_col>":  { "date": "2026-07-20", "time": "09:15:00" },
  "<closed_col>":    { "date": "2026-07-22", "time": "11:02:00" },
  "<comments_col>":  12,
  "<branch_col>":    "feat/auth-fix → main",
  "<linked_col>":    "#98",
  "<synced_col>":    { "date": "2026-07-24", "time": "18:00:00" },
  "<people_col>":    { "personsAndTeams": [ { "id": 12345678, "kind": "person" } ] }
}
```

Notes that will bite otherwise:

- **Date columns take an optional `time`** in UTC, `HH:MM:SS`. If a write is
  rejected for the `time` key, retry date-only and note the degraded precision
  in the run summary. Do not silently drop it.
- **Write UTC; never pre-convert to local.** monday stores exactly the UTC you
  submit and renders per-account timezone on read. Verified: submitting
  `{"date":"2026-07-24","time":"19:05:15"}` stores that value and renders as
  `2026-07-24 14:05` on a UTC-5 account. The stored data is correct; only the
  display shifts.
- **When diffing, read `value`, never `text`.** A column's `text` field is the
  locally-rendered string; `value` is the raw UTC JSON. For a GitHub timestamp
  of `19:05:15Z` written to a UTC-5 account:

  ```
  text  → "2026-07-24 14:05"                              ← local, do NOT compare
  value → {"date":"2026-07-24","time":"19:05:15"}          ← UTC, compare this
  ```

  Comparing `text` against a GitHub UTC timestamp mismatches on every run for
  any account not on UTC, so every item looks changed and the sync rewrites the
  whole board forever. This is the single easiest way to turn an incremental
  sync into a full one.
- **Status and dropdown labels must exist** or the write throws
  `ColumnValueException`. Pass `createLabelsIfMissing: true` when setting
  `Labels` (GitHub labels are open-ended) and on the retry path for `Type` /
  `GitHub State`.
- **Clearing a value** needs an explicit empty: `""` for text, `{}` for date
  and link. Omitting the key leaves the old value in place — which is how a
  reopened issue keeps a stale `Closed / Merged At`.
- **Empty string is not null for dates.** Use `{}`.

## State label mapping

| GitHub | `GitHub State` |
|---|---|
| issue open | `Open` |
| issue closed | `Closed` |
| PR open, not draft | `Open` |
| PR open, draft | `Draft` |
| PR closed, `merged_at` set | `Merged` |
| PR closed, no `merged_at` | `Closed` |

Suggested colors when creating the `GitHub State` column: `Open` green,
`Draft` grey, `Merged` purple, `Closed` dark red — matching GitHub's own
palette so the board reads the same way as the repo.

## No monday assignment

This skill does not touch any people column — not `Person`, not `Owner`, not
`Assignee`. A GitHub issue has no opinion about who should own the monday row,
and inventing one puts work in somebody's "My Work" queue on the strength of a
guess.

Rows arrive unowned. Assigning them is a human decision made on the board.

**GitHub assignees are not mapped to monday users either.** There is no
reliable GitHub-login → monday-user mapping, and guessing by name assigns work
to the wrong person. GitHub assignees stay in the `GitHub Assignees` text
column, as text.

## The Author column names a person, never a bot

`Author` carries the human accountable for the change. A `[bot]` identity never
appears there: no one's account pushed it, and "who filed this" is not what a
PM is reading the column for.

Most items need no special handling — work pushed through a harness is authored
by the developer's own GitHub account, with the tool recorded only as a
`Co-Authored-By` trailer. Only genuine third-party apps install under their own
identity. For those, `scripts/resolve-authors.py` walks GitHub for a human who
actually touched the item; see its docstring for the chain.

Bot-ness stays visible through `Labels`, which carries real GitHub labels
(`dependencies`, `github_actions`). That is a searchable fact about the change
rather than something this skill invents, so a PM can still find every
dependency bump without a bot's name sitting in an authorship field.
