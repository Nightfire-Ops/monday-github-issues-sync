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


def display_author(login, automation_author=None):
    """Resolve the display attribution for an event author.

    Strips a trailing [bot] suffix. When automation_author is set, an author
    carrying that suffix is re-attributed to it instead — an ownership override
    configured per installation, never hardcoded.

    Nothing downstream may branch on bot-ness for formatting: the returned name
    is rendered identically regardless of how it was resolved.
    """
    login = login or ""
    if automation_author and login.endswith("[bot]"):
        return automation_author
    return re.sub(r"\[bot\]$", "", login)


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
        body = re.sub(
            r"(?<![\w#/])#(\d+)\b",
            rf'<a href="https://github.com/{repo}/issues/\1">#\1</a>',
            body,
        )
    return body


def truncate(body, url):
    if len(body) <= MAX_BODY:
        return body
    cut = body[:MAX_BODY].rsplit("<br/>", 1)[0]
    return f'{cut}… <a href="{url}">read the full comment on GitHub</a><br/>'


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

    # The marker makes the posted feed self-describing: a later run can rebuild
    # syncedEvents by reading updates back, without the state file. Invisible in
    # the monday UI. See references/reconciliation.md.
    parts = [
        f'<div><!-- gh-event:{ev["key"]} -->',
        f'<b>[{fmt_ts(ev["at"])}] {glyph} {header}</b><br/>',
    ]
    if ev["kind"] == "opened":
        parts.append(
            f'<i>Synced from <a href="{ev["url"]}">{repo}#{ev["number"]}</a></i>'
            "<br/><br/>"
        )
    parts.append(truncate(md_to_html(ev.get("body"), repo), ev["url"]))
    parts.append(f'<a href="{ev["url"]}">View on GitHub →</a>')
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
        ev["html"] = render(ev, repo, automation_author)

    # Oldest-first within each item, so the monday feed reads chronologically
    # even though monday stamps every entry with the time it was posted.
    events.sort(key=lambda e: (e["number"], e["at"]))
    json.dump(events, sys.stdout, indent=1, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
