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
| `Person` / `Owner` | `people` | monday user assigned on create — see below | only when `assignTo` is set |

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

## Assignment

Without an assignee, every synced row lands unowned and somebody has to go
through the board assigning them by hand. Set `options.assignTo` in state to
avoid that:

| `assignTo` | Behaviour |
|---|---|
| `"me"` | resolve the authenticated monday user via `get_user_context` and assign them |
| a numeric user id | assign that user |
| `null` (default) | do not touch any people column |

Resolve `"me"` **once per run**, at Step 1, and cache the numeric id in
`columnMap`-adjacent state — do not call `get_user_context` per item.

**Which column.** Look for an existing `people`-type column titled `Person`,
`Owner`, or `Assignee`, case-insensitively, and reuse the first match. A
default monday board ships with `Person`, which is the column that feeds "My
Work" and monday's own notifications — reusing it is what makes assignment
actually useful. Create `Owner` only if no people column exists at all.

This is the one default column the skill will write to, and only when
`assignTo` is set. `Status` and `Date` are still never touched.

**Payload shape** — a people column takes ids, never names:

```json
{ "personsAndTeams": [ { "id": 12345678, "kind": "person" } ] }
```

`kind` is `"person"` or `"team"`. Passing a display name silently produces an
empty cell rather than an error, so always resolve to an id first.

**GitHub assignees are not mapped to monday users.** There is no reliable
GitHub-login → monday-user mapping, and guessing by name assigns work to the
wrong person. GitHub assignees stay in the `GitHub Assignees` text column;
`assignTo` controls the monday people column independently.
