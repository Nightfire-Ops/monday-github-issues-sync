# Feed entry format

Every GitHub event becomes one monday update via `create_update`. This is the
part a PM actually reads, so format discipline matters more here than anywhere
else in the skill.

**`scripts/render-entries.py` implements everything below.** Call it instead of
converting by hand; this document is the specification it satisfies and the
reference for changing it.

```bash
scripts/render-entries.py OWNER/REPO < events.json > bodies.json
```

## The timestamp problem

`create_update` **does** expose an `original_creation_date` argument — but it is
silently ignored on this path. Verified against a live account with three
variants (ISO-8601 with `Z`, ISO plus `use_app_info: true`, and a bare
`YYYY-MM-DD`): every one returned a `created_at` of *now*. The argument is
presumably honoured only for app/integration contexts the MCP server does not
provide.

So in practice monday stamps every update with the time it was posted, and a
backfill of two years of history lands entirely on today's date. Do not spend
time trying to make `original_creation_date` work — it has been tested.

Mitigations, all three applied together:

1. **Every body opens with the GitHub timestamp in bold**, `YYYY-MM-DD HH:MM UTC`.
   That is the authoritative time; monday's own stamp is noise.
2. **Post oldest-first** so the feed's own ordering matches reality.
3. **Item date columns** (`Opened At`, `Last Activity`, `Closed / Merged At`)
   carry real GitHub times and are what board views, filters, and dashboards
   should be built on. Never build a monday view on update `created_at`.

Say this out loud to the user on first run. Someone will otherwise build a
"development activity over time" dashboard on the wrong timestamp and get a
single spike on backfill day.

## Body is HTML, not markdown

`create_update` takes HTML. Markdown passes through as literal characters.
GitHub comment bodies are markdown and must be converted.

Minimum viable conversion — do these, skip the rest:

| GitHub markdown | HTML |
|---|---|
| `` `code` `` | `<code>code</code>` |
| ```` ```block``` ```` | `<pre>block</pre>` |
| `**bold**` | `<b>bold</b>` |
| `*italic*` | `<i>italic</i>` |
| `## Heading` | `<b>Heading</b><br/>` |
| `[text](url)` | `<a href="url">text</a>` |
| bare URL | `<a href="url">url</a>` |
| `- item` (run of lines) | `<ul><li>item</li>…</ul>` |
| `1. item` (run of lines) | `<ol><li>item</li>…</ol>` |
| line break | `<br/>` |
| `#123` | `<a href="https://github.com/OWNER/REPO/issues/123">#123</a>` |
| `@user` | plain text `@user` |

**Headings and lists need line-level handling, not a single `gsub`.** Issue
bodies are full of `## Question` / `## Decision` structure and bulleted
resolutions. A naive inline substitution leaves `##` and `-` as literal
characters in the feed — verified against real data. Walk the body line by
line: convert heading lines, and group consecutive `-`/`1.` lines into one
list element before joining the rest with `<br/>`.

**Apply the same conversion to every event type.** Comment bodies, review
bodies, and the issue/PR body all come from the same markdown source. Running
the full conversion on the opened-entry but only HTML-escaping comments is an
easy slip, and it shows up as raw `**bold**` scattered through the feed.

**Do not cross-link `#NNN` inside quoted upstream content.** Dependency-bump
PRs embed another project's release notes inside `<details>` blocks, and those
`#408`-style references belong to *that* repo. Linkifying them points a PM at
the wrong repository's issue — verified in a real sync. The renderer skips
`#NNN` linkification entirely when the body contains an escaped `<details>`.

**Convert images before links.** `![alt](url)` also matches the link pattern
and yields a malformed nested anchor. Images run first and degrade to a plain
labelled link — a badge adds nothing to a PM feed.

**Escape `<`, `>`, `&` in the comment text before wrapping it in HTML.** Issue
comments routinely contain stack traces, generics, and XML; unescaped they
break the update body or vanish silently.

**Never convert `@user` into a monday mention.** `mentionsList` notifies real
people — a backfill would fire hundreds of notifications at whoever's monday
account happens to match. Leave GitHub handles as plain text.

## Attribution

Every entry is attributed to **the GitHub login that actually submitted it**,
taken from the event's own `user.login`. Never attribute to the account running
the sync, and never hardcode an account anywhere in this skill — the person
running it is frequently not the person who wrote the comment.

Normalize the login for display:

```
dependabot[bot]      → dependabot
renovate[bot]        → renovate
github-actions[bot]  → github-actions
<login>              → <login>          (unchanged)
```

Strip a trailing `[bot]` suffix and display the bare login. Do **not** add a
"bot" badge, glyph, suffix, or separate grouping, and do not branch feed
formatting on whether an author is automated. Automated contributions are real
contributions; they are attributed to their author exactly like any other, and
the board reads uniformly.

The un-normalized login stays in the state file for matching. Only the display
form is stripped.

### Ownership override

Some teams want automated activity attributed to the person accountable for the
repository rather than to the service that opened it — a dependency-bump PR
shows up under the maintainer who owns the upgrade, not under the bot.

Attribution resolves to a human before rendering — see
`scripts/resolve-authors.py`. `automationAuthor` is the fallback for when
GitHub yields nobody:

```json
"options": { "automationAuthor": "<login>" }
```

When set, any event whose raw author carries a `[bot]` suffix is attributed to
that login instead. When unset (the default), the real submitter is used.

This is an **ownership** view, not an authorship claim: the named person did not
write the change. Set it deliberately, and never hardcode a login in the skill —
it is a per-installation value that lives only in the user's state file.

## Length

Cap bodies at ~2,000 characters and truncate at a line boundary, ending with a
bare `…`. Long comments are usually logs, and the value in monday is knowing
the exchange happened.

**Exactly one footer link per entry.** When the body was cut, the single footer
link carries that fact — it does not get a second link beside it:

| Body | Footer |
|---|---|
| complete | `View on GitHub →` |
| truncated, comment | `Read the full comment on GitHub →` |
| truncated, issue/PR body | `Read the full description on GitHub →` |

Having truncation append its own "read more" link *and* the footer append
"View on GitHub" produced two links to the same URL on every truncated entry —
reported from a live board after 22 of 50 entries shipped that way. Truncation
returns `(text, was_truncated)`; the caller picks the label.

## Entry template

```html
<div>
<b>[2026-07-20 14:32 UTC] 💬 Comment — alice</b><br/>
Looks good, but this needs to handle the null case before merge.<br/>
<a href="https://github.com/owner/repo/issues/123#issuecomment-445566">View on GitHub →</a>
</div>
```

## Event types

| Event | Glyph | Header |
|---|---|---|
| opened | 🆕 | `Opened by <login>` |
| comment | 💬 | `Comment — <login>` |
| review: approved | ✅ | `Approved — <login>` |
| review: changes requested | 🔴 | `Changes requested — <login>` |
| review: commented | 🔍 | `Review — <login>` |
| inline review comment | 📝 | `Review comment on <file>:<line> — <login>` |
| merged | 🔀 | `Merged by <login> into <base>` |
| closed | ⛔ | `Closed by <login>` (add ` as not planned` when `state_reason` says so) |
| reopened | ♻️ | `Reopened by <login>` |
| commit | 📦 | `Commit <sha7> — <login>` |
| labeled | 🏷️ | `Label added: <name>` |
| unlabeled | 🏷️ | `Label removed: <name>` |
| assigned | 👤 | `Assigned to <login>` |
| unassigned | 👤 | `Unassigned <login>` |
| renamed | ✏️ | `Renamed: "<old>" → "<new>"` |
| cross-referenced | 🔗 | `Referenced by <#num> — <title>` |

Glyphs are load-bearing: they let a PM scan a feed and see the shape of the
work without reading it. Keep the mapping stable across runs.

## First entry on a newly created item

The first update posted to a new item is the issue/PR body, and it carries the
provenance the columns cannot:

```html
<div>
<b>[2026-07-01 09:00 UTC] 🆕 Opened by alice</b><br/>
<i>Synced from <a href="https://github.com/owner/repo/issues/123">owner/repo#123</a></i><br/><br/>
When the auth middleware receives a request with no session cookie, it
dereferences <code>session.user</code> and throws.<br/>
</div>
```

If the item's backfill was truncated by the per-item cap, append to this first
entry — do not bury it in a separate update:

```html
<br/><i>⚠️ History truncated: showing the 40 most recent of 137 events.
<a href="https://github.com/owner/repo/issues/123">Full history on GitHub</a></i>
```

## Ordering within a run

Sort all events for an item by GitHub timestamp ascending before posting.
Where timestamps tie (a review and its inline comments land on the same
second), order: review → inline comments → state change. Post sequentially,
not concurrently — concurrent `create_update` calls arrive out of order and
the feed reads scrambled.
