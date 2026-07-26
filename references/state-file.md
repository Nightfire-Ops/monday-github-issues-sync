# Sync state file

Path: `.monday-sync/<owner>-<repo>--board-<boardId>.json`

**Commit this file.** It is the only thing preventing duplicate items on the
next run, and it needs to survive across machines and CI.

One file per (repo, board) pair — the same repo can sync to several boards, and
the same board can receive several repos.

## Schema

```json
{
  "version": 1,
  "repo": "owner/repo",
  "boardId": 1234567890,
  "boardName": "Engineering",
  "lastSyncedAt": "2026-07-24T18:00:00Z",
  "autoApprove": false,
  "options": {
    "automationAuthor": null,
    "excludeAuthors": [],
    "syncCommits": false,
    "syncLabelEvents": false,
    "maxItemsPerRun": 100,
    "maxEntriesPerItemBackfill": 40,
    "maxEntriesPerRun": 1500
  },
  "columnMap": {
    "githubUrl":  "link_mkabc123",
    "type":       "color_mkabc124",
    "state":      "color_mkabc125",
    "author":     "text_mkabc126",
    "assignees":  "text_mkabc127",
    "labels":     "dropdown_mkabc128",
    "milestone":  "text_mkabc129",
    "openedAt":   "date_mkabc130",
    "activityAt": "date_mkabc131",
    "closedAt":   "date_mkabc132",
    "comments":   "numeric_mkabc133",
    "branch":     "text_mkabc134",
    "linked":     "text_mkabc135",
    "lastSynced": "date_mkabc136"
  },
  "groupMap": {
    "issues": "topics",
    "prs":    "group_title_abc"
  },
  "itemMap": {
    "issue/123": {
      "mondayItemId": 987654321,
      "updatedAt": "2026-07-20T09:15:00Z",
      "lastEventAt": "2026-07-20T09:15:00Z",
      "syncedEvents": ["comment:445566", "state:closed@2026-07-20T09:15:00Z"],
      "truncatedBackfill": false
    },
    "pr/45": {
      "mondayItemId": 987654322,
      "updatedAt": "2026-07-22T11:02:00Z",
      "lastEventAt": "2026-07-22T11:02:00Z",
      "syncedEvents": ["review:778899", "comment:445599", "state:merged@2026-07-22T11:02:00Z"],
      "truncatedBackfill": true
    }
  },
  "flagged": [
    { "key": "issue/17", "reason": "404 on GitHub — deleted or transferred", "at": "2026-07-24T18:00:00Z" }
  ]
}
```

## Field notes

- **`lastSyncedAt`** — the watermark passed as `since` to GitHub. Set it to the
  time captured *before* fetching, not after writing. Setting it to the finish
  time silently drops any event that landed mid-run.
- **`columnMap`** — monday generates column ids on creation. These are the only
  reliable handle; never address a column by title after Step 3.
- **`itemMap` keys** — `issue/<number>` and `pr/<number>`. Namespaced because a
  repo can have issue #45 and PR #45.
- **`syncedEvents`** — the idempotency set for the Updates feed. An event is
  posted only if its key is absent here.
- **`truncatedBackfill`** — set when the per-item entry cap dropped history.
  Surface these in the run summary; they are the items where the monday feed is
  knowingly incomplete.
- **`automationAuthor`** — a GitHub login, or `null`. The **last resort** for
  attributing a `[bot]`-authored item, used only when GitHub yields no human:
  `scripts/resolve-authors.py` first tries the opener, the merger, whoever
  enabled auto-merge, and the first approver. Set it to whoever is accountable
  for automation. Never hardcode it in the skill — it is per-installation, it
  lives only here, and `packaging/verify-portable.sh` fails if any value from
  this file appears in the skill surface.
- **`excludeAuthors`** — GitHub logins whose issues and PRs are not mirrored.
  Empty by default. Matching folds case and treats a trailing `[bot]` as
  optional on both sides, so `"depbot"` and `"depbot[bot]"` are the same
  filter — a user configures the name they see in the UI. Blank entries never
  match, so a stray `""` cannot exclude everything, and an item whose author
  GitHub omitted (deleted account) is never excluded. See *Exclusion is
  item-scoped* below.
- **`autoApprove`** — when true, skip the Step 5 confirmation. Intended for
  scheduled runs. Set it deliberately, not as a convenience during setup.

## Exclusion is item-scoped

`excludeAuthors` decides which issues and PRs become board items. It does
**not** filter feed entries. An excluded author commenting on somebody else's
issue is part of that conversation — dropping the comment would remove context
from an item the filter never named.

Three consequences worth knowing before setting it:

- **Rows already on the board stay.** An item that predates the exclusion is
  reported with its monday id and then left alone: not updated, and never
  removed. Removal is a proposal to a human like every other deletion.
- **Its state entry is kept too.** Nothing is discarded, so clearing the
  exclusion resumes normal syncing for that item immediately.
- **Un-excluding does not backfill.** `lastSyncedAt` advanced past those items
  while they were filtered, so an incremental run will not see them again. To
  bring them in, clear `lastSyncedAt` and let the next run do a full pass —
  reconciliation makes that safe, it will not duplicate what is already there.

## Event keys

Stable, derived from GitHub ids so they survive edits and re-fetches:

| Event | Key |
|---|---|
| issue/PR comment | `comment:<comment_id>` |
| PR review | `review:<review_id>` |
| PR inline review comment | `rcomment:<comment_id>` |
| commit on a PR | `commit:<sha7>` |
| state change | `state:<open\|closed\|merged\|reopened>@<iso>` |
| label change | `label:<+\|-><name>@<iso>` |
| assignment | `assign:<+\|-><login>@<iso>` |
| item opened | `opened@<iso>` |

State and label keys embed a timestamp because the same transition can happen
more than once (close → reopen → close) and each occurrence is its own entry.

Comment ids are stable across edits, so an edited GitHub comment is **not**
re-posted. That is deliberate — re-posting on every edit floods the feed. If a
user needs edit history in monday, sync it as a distinct
`comment:<id>:edited@<iso>` key rather than reusing the original.

## Growth

`syncedEvents` grows without bound on busy items. If a file passes ~2 MB,
compact it: keep the 200 most recent keys per item and rely on `lastEventAt` as
the cutoff for anything older. Record `compactedAt` on the item when you do,
so a later reader knows why the list is short.

## Recovery

**State file lost, board already populated.** Do not re-run blind — it will
duplicate every item. Rebuild instead: page the board with
`get_board_items_page` including the `GitHub URL` column, parse `owner/repo` and
the number out of each URL, and reconstruct `itemMap` with `syncedEvents: []`
and `lastEventAt` set to now. Feed history before that point is not
recoverable, but no duplicate items are created and future events sync
correctly.

**Duplicates already created.** Group board items by their `GitHub URL` value,
keep the oldest of each group, and report the rest for the user to archive.
Never auto-delete monday items — they may carry human comments this skill did
not write.
