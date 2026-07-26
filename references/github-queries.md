# GitHub extraction

All commands assume `OWNER/REPO` and `gh` authenticated with repo read access.
Write output to the scratchpad as JSON; parse with `jq`. Do not hold full fetch
results in context.

## Why not per-item timelines

`gh api repos/O/R/issues/N/timeline` gives the richest data but costs one
paginated request **per item**. For a 300-issue backfill that is 300+ requests
before you have posted anything.

The repo-wide comment endpoints return every comment across every issue and PR
in a handful of paginated calls, each carrying `issue_url` so you can bucket
them locally. Use those for backfill and for incremental. Reach for per-item
timelines only for the one case they uniquely cover — see *Label and assignment
events* below.

## Issues and PRs

GitHub's issues endpoint returns pull requests too. One call covers both;
entries with a `pull_request` key are PRs.

```bash
# Full backfill — every issue and PR, any state
gh api "repos/OWNER/REPO/issues?state=all&sort=updated&direction=asc&per_page=100" \
  --paginate > "$SCRATCH/issues.json"

# Incremental — only what changed since the watermark
gh api "repos/OWNER/REPO/issues?state=all&since=2026-07-01T00:00:00Z&sort=updated&direction=asc&per_page=100" \
  --paginate > "$SCRATCH/issues.json"
```

`since` filters on `updated_at`, so it catches new comments, label changes,
and state changes — not just edits to the body.

PRs need fields the issues endpoint does not return (`merged_at`, `draft`,
`head`/`base`). Fetch those separately and join on number:

```bash
gh api "repos/OWNER/REPO/pulls?state=all&sort=updated&direction=asc&per_page=100" \
  --paginate \
  --jq '[.[] | {number, draft, merged_at, head: .head.ref, base: .base.ref}]' \
  > "$SCRATCH/prs.json"
```

The `pulls` endpoint has no `since` parameter. On incremental runs, restrict
the join to PR numbers already identified as changed by the issues call rather
than paginating all PRs.

## Comments

```bash
# Issue + PR conversation comments, repo-wide
gh api "repos/OWNER/REPO/issues/comments?sort=updated&direction=asc&per_page=100" \
  --paginate > "$SCRATCH/comments.json"

# PR review comments (inline, on a diff line)
gh api "repos/OWNER/REPO/pulls/comments?sort=updated&direction=asc&per_page=100" \
  --paginate > "$SCRATCH/review-comments.json"
```

Both accept `&since=<iso8601>` for incremental runs. Bucket by number parsed
from `issue_url` / `pull_request_url`.

## Reviews

Reviews (approve / request changes / comment) have no repo-wide endpoint —
they are per-PR. Fetch only for PRs the diff already flagged as changed:

```bash
gh api "repos/OWNER/REPO/pulls/NUMBER/reviews?per_page=100" --paginate \
  --jq '[.[] | {id, state, user: .user.login, submitted_at, body}]'
```

## Commits on a PR

Only worth syncing if the user wants commit-level visibility — it is noisy and
multiplies feed entries. Off by default; ask before enabling.

```bash
gh api "repos/OWNER/REPO/pulls/NUMBER/commits?per_page=100" --paginate \
  --jq '[.[] | {sha: .sha[0:7], message: .commit.message, date: .commit.author.date, author: .commit.author.name}]'
```

## Label and assignment events

The only data the repo-wide endpoints do not cover. If the user wants "who was
assigned when" and "when was p1 added" in the feed, this needs the per-item
timeline — accept the cost, and only for changed items:

```bash
gh api "repos/OWNER/REPO/issues/NUMBER/timeline?per_page=100" --paginate \
  --jq '[.[] | select(.event | IN("labeled","unlabeled","assigned","unassigned","milestoned","renamed","closed","reopened","merged","cross-referenced"))]'
```

Off by default. When off, label and assignee state still reaches monday via
the item's columns — you lose the history of *when* it changed, not the
current value.

## Linked issues and PRs

Populates the `Linked` column. For a PR, its closing references:

```bash
gh pr view NUMBER --repo OWNER/REPO --json closingIssuesReferences \
  --jq '[.closingIssuesReferences[].number]'
```

For an issue, PRs that reference it come from `cross-referenced` events in the
timeline, or cheaply by scanning fetched PR bodies for `#<number>` and
`closes/fixes/resolves #<number>`. The scan is approximate but free — prefer it
unless the user needs precision.

## Rate limits

Check before a large backfill; report the reset time rather than retrying into
a wall:

```bash
gh api rate_limit --jq '.resources.core | {remaining, reset: (.reset | todate)}'
```

The authenticated REST budget is 5,000 requests/hour. A backfill of a few
hundred items using the repo-wide endpoints lands in the low tens of requests —
per-item timelines are what put a run at risk.

## Deleted and transferred items

An item in state that now 404s was deleted or transferred. Flag it in the run
summary and leave the monday item untouched. Never auto-archive: a transfer is
not a cancellation, and PMs rely on those rows.
