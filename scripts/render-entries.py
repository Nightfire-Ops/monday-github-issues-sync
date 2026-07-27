#!/usr/bin/env python3
"""Render GitHub events as monday.com update bodies.

Implements references/update-format.md. Deterministic and offline — no network,
no credentials, nothing account-specific. Exists because the markdown → HTML
conversion has non-obvious failure modes (headings and lists need line-level
handling; escaping must precede tag insertion) that are easy to re-break.

Usage:
    render-entries.py OWNER/REPO [--automation-author LOGIN] < events.json > out.json

--automation-author re-attributes events whose raw author carries a [bot]
suffix to the given login. This is an ownership view (who is accountable for
the change), not an authorship claim. Omit it to use the real submitter.

Input: JSON array of events, each:
    {"kind": "opened"|"comment"|"review"|...,   # key of GLYPH below
     "number": 123,                             # GitHub issue/PR number
     "at": "2026-07-01T14:32:00Z",              # GitHub UTC timestamp
     "author": "somelogin",                     # raw login; [bot] stripped here
     "body": "markdown…",
     "url": "https://github.com/OWNER/REPO/issues/123#issuecomment-1",
     "header": "Comment"}                       # optional; defaults per kind

Output: the same array, each event gaining "html" (the monday update body) and
"key" (the idempotency key), sorted oldest-first within each number.
"""
import html
import json
import re
import sys

MAX_BODY = 2000

GLYPH = {
    "opened": ("🆕", "Opened by {author}"),
    "comment": ("💬", "Comment — {author}"),
    "review_approved": ("✅", "Approved — {author}"),
    "review_changes": ("🔴", "Changes requested — {author}"),
    "review_comment": ("🔍", "Review — {author}"),
    "inline_comment": ("📝", "Review comment — {author}"),
    "merged": ("🔀", "Merged by {author}"),
    "closed": ("⛔", "Closed by {author}"),
    "reopened": ("♻️", "Reopened by {author}"),
    "commit": ("📦", "Commit — {author}"),
    "labeled": ("🏷️", "Label added"),
    "unlabeled": ("🏷️", "Label removed"),
    "assigned": ("👤", "Assigned to {author}"),
    "unassigned": ("👤", "Unassigned {author}"),
    "renamed": ("✏️", "Renamed"),
    "cross_referenced": ("🔗", "Referenced"),
}


# Event kinds that never carry a body of their own. Anything not listed here is
# expected to have one, so its absence is worth stating rather than hiding.
BODILESS = frozenset({
    "merged", "closed", "reopened", "labeled", "unlabeled",
    "assigned", "unassigned", "renamed", "cross_referenced",
})


class UnresolvedAuthor(Exception):
    """A bot identity reached the renderer with no human to attribute it to."""


def display_author(login, automation_author=None):
    """Resolve the display attribution for an event author.

    The Author column and every feed header name a **person, never a bot**. A
    `[bot]` identity is not an author — no one's account pushed it — so it is
    replaced by the human accountable for that automation.

    Normally the author arriving here is already resolved by
    `resolve-authors.py`, which walks GitHub for whoever merged, enabled
    auto-merge, or approved. This is the backstop for anything that slipped
    past: an unattributable bot raises rather than being written to the board.
    Stripping the suffix and shipping `dependabot` was the old behaviour and is
    exactly what must not happen.

    Nothing downstream may branch on bot-ness for *formatting*: once resolved,
    the name renders identically however it was arrived at.
    """
    login = login or ""
    if login.endswith("[bot]"):
        if automation_author and not automation_author.endswith("[bot]"):
            return automation_author
        raise UnresolvedAuthor(
            f"{login!r} has no human attribution. Resolve it with "
            "resolve-authors.py, or set options.automationAuthor."
        )
    return login


def fmt_ts(iso):
    """2026-07-01T14:32:00Z -> '2026-07-01 14:32 UTC'. Always UTC, never local."""
    return iso.replace("T", " ")[:16] + " UTC"


def md_to_html(body, repo):
    """Convert GitHub markdown to the HTML subset monday updates accept.

    Order matters: escape first, then fenced code, then block structure
    (headings/lists) line by line, then inline spans. Doing inline before block
    leaves list markers and heading hashes as literal characters.
    """
    if not body or not body.strip():
        return "<i>(no description)</i><br/>"

    body = html.escape(body, quote=False)
    body = re.sub(r"```[a-zA-Z0-9]*\n?(.*?)```", r"<pre>\1</pre>", body, flags=re.S)

    out, buf, kind = [], [], None

    def flush():
        nonlocal buf, kind
        if buf:
            out.append(
                f"<{kind}>" + "".join(f"<li>{x}</li>" for x in buf) + f"</{kind}>"
            )
        buf, kind = [], None

    for line in body.split("\n"):
        s = line.strip()
        if m := re.match(r"^#{1,6}\s+(.*)", s):
            flush()
            out.append(f"<b>{m.group(1)}</b><br/>")
        elif m := re.match(r"^[-*+]\s+(.*)", s):
            if kind == "ol":
                flush()
            kind = "ul"
            buf.append(m.group(1))
        elif m := re.match(r"^\d+\.\s+(.*)", s):
            if kind == "ul":
                flush()
            kind = "ol"
            buf.append(m.group(1))
        else:
            flush()
            out.append(s + "<br/>")
    flush()
    body = "".join(out)

    body = re.sub(r"`([^`]+)`", r"<code>\1</code>", body)
    body = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", body)
    # Images first: ![alt](url) would otherwise match the link rule and produce
    # a malformed "![alt</a>](...)" fragment. monday updates render <img>, but a
    # badge adds nothing to a PM feed, so it degrades to a plain labelled link.
    body = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<a href="\2">\1</a>', body)
    body = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', body)
    # Markdown link-reference definitions are invisible in GitHub's render and
    # are pure noise in a feed.
    body = re.sub(r"\[//\]: # \([^)]*\)(<br/>)?", "", body)
    # Only cross-link #NNN when the body is the author's own prose. Bodies that
    # embed an upstream changelog — dependency-bump PRs quote release notes
    # inside <details> blocks — reference *another* repo's issue numbers, and
    # linkifying those points at the wrong repository. Verified: an upstream
    # "#408" rendered as a link to this repo's issue 408.
    if "&lt;details&gt;" not in body:
        # Mask existing anchors before linkifying. A markdown link whose text
        # already contains "#8" would otherwise get a second <a> nested inside
        # the first — invalid HTML that renders as a broken double link.
        # Observed live on an issue body reading "[Wayfinder map #8](...)".
        anchors = []

        def _stash(m):
            anchors.append(m.group(0))
            return f"\x00A{len(anchors) - 1}\x00"

        body = re.sub(r"<a\b[^>]*>.*?</a>", _stash, body, flags=re.S)
        body = re.sub(
            r"(?<![\w#/])#(\d+)\b",
            rf'<a href="https://github.com/{repo}/issues/\1">#\1</a>',
            body,
        )
        body = re.sub(r"\x00A(\d+)\x00", lambda m: anchors[int(m.group(1))], body)
    return body


def truncate(body):
    """Cut an over-long body at a line boundary.

    Returns (text, was_truncated). It deliberately does NOT append its own
    "read more" link: render() always adds exactly one footer link, and having
    truncate() add a second produced two links to the same URL on every
    truncated entry — reported from a live board.
    """
    if len(body) <= MAX_BODY:
        return body, False
    cut = body[:MAX_BODY].rsplit("<br/>", 1)[0]
    return f"{cut}…<br/>", True


def event_key(ev):
    kind, at = ev["kind"], ev["at"]
    if gid := ev.get("id"):
        return {
            "comment": f"comment:{gid}",
            "review_approved": f"review:{gid}",
            "review_changes": f"review:{gid}",
            "review_comment": f"review:{gid}",
            "inline_comment": f"rcomment:{gid}",
            "commit": f"commit:{gid}",
        }.get(kind, f"{kind}:{gid}")
    if kind == "opened":
        return f"opened@{at}"
    return f"state:{kind}@{at}"


def render(ev, repo, automation_author=None):
    glyph, default_header = GLYPH.get(ev["kind"], ("•", "{author}"))
    author = display_author(ev.get("author"), automation_author)
    header = (ev.get("header") or default_header).format(author=author)

    # No HTML-comment marker here: monday's sanitiser strips <!-- --> from
    # update bodies, verified by reading posted updates back. The durable
    # identifier is the footer link's href, which carries #issuecomment-<id>
    # and survives sanitisation. See references/reconciliation.md.
    parts = [
        "<div>",
        f'<b>[{fmt_ts(ev["at"])}] {glyph} {header}</b><br/>',
    ]
    if ev["kind"] == "opened":
        parts.append(
            f'<i>Synced from <a href="{ev["url"]}">{repo}#{ev["number"]}</a></i>'
            "<br/><br/>"
        )
    # State changes carry no body, so the "(no description)" placeholder would
    # report an absence that was never possible. An *opened* item with an empty
    # description is the opposite case — that emptiness is real, and shown.
    if ev.get("body") or ev["kind"] not in BODILESS:
        text, was_truncated = truncate(md_to_html(ev.get("body"), repo))
        parts.append(text)
    else:
        was_truncated = False

    # Exactly ONE footer link per entry. When the body was cut, the link carries
    # that fact instead of adding a second link beside it.
    if was_truncated:
        what = "description" if ev["kind"] == "opened" else "comment"
        label = f"Read the full {what} on GitHub →"
    else:
        label = "View on GitHub →"
    parts.append(f'<a href="{ev["url"]}">{label}</a>')
    parts.append("</div>")
    return "".join(parts)


def main():
    args = sys.argv[1:]
    automation_author = None
    if "--automation-author" in args:
        i = args.index("--automation-author")
        try:
            automation_author = args[i + 1]
        except IndexError:
            sys.exit("--automation-author requires a GitHub login")
        del args[i:i + 2]
    if len(args) != 1 or "/" not in args[0]:
        sys.exit(
            "usage: render-entries.py OWNER/REPO [--automation-author LOGIN]"
            " < events.json"
        )
    repo = args[0]
    events = json.load(sys.stdin)

    for ev in events:
        ev["key"] = event_key(ev)          # must precede render(); embedded in body
        try:
            ev["html"] = render(ev, repo, automation_author)
        except UnresolvedAuthor as exc:
            # Fail the whole run, not this entry. Skipping it would post a
            # partial feed and hide the misconfiguration behind a gap.
            sys.exit(f"render-entries.py: #{ev.get('number')}: {exc}")

    # Oldest-first within each item, so the monday feed reads chronologically
    # even though monday stamps every entry with the time it was posted.
    events.sort(key=lambda e: (e["number"], e["at"]))
    json.dump(events, sys.stdout, indent=1, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
