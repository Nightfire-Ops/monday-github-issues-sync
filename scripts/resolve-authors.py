#!/usr/bin/env python3
"""Resolve the human GitHub account behind each issue and pull request.

The Author column names a **person, never a bot**. A `[bot]` identity is not an
author: no one's account pushed it, and a PM reading the board needs to know
who owns the change, not which service filed it. Bot-ness stays discoverable
through the Labels column, which carries real GitHub labels.

Most items need no work. Anything pushed through a harness — Claude Code or
similar — is authored by the developer's own GitHub account, with the tool
recorded only as a `Co-Authored-By` trailer. `user.login` is already the person.
Only genuine third-party apps (dependabot and friends) install under their own
identity, and for those this walks GitHub for a human who actually touched the
item:

    1. opener        user.login, when it is not a bot
    2. merged_by     who merged the PR
    3. auto_merge    who enabled auto-merge (the merger is often a bot)
    4. approver      the first human APPROVED review
    5. configured    options.automationAuthor — last resort

When every step comes up empty the answer is **None**, not the bot login.
Verified against a live repo: seven open dependabot PRs had merged_by,
auto_merge.enabled_by and reviews all null — nobody had touched them, so there
was genuinely no human to find. That is what step 5 is for.

Usage:
  resolve-authors.py --github issues.json [--details details.json] \
                     [--reviews reviews.json] [--fallback LOGIN]

details.json : {"<number>": <repos/O/R/pulls/N response>, ...}
reviews.json : {"<number>": <repos/O/R/pulls/N/reviews response>, ...}

Only bot-authored PRs need those two files — see needs_detail(). Emits the
input array on stdout with `resolvedAuthor` and `authorSource` added, and a
summary on stderr. Read-only and offline; it decides, it does not fetch.
"""
import argparse
import json
import sys
from collections import Counter


def is_bot(login):
    """True for a GitHub app identity.

    Matches the `[bot]` suffix only. A substring test would catch `robotics`
    and `botany`, silently reassigning a real person's work.
    """
    return bool(login) and login.endswith("[bot]")


def _human(login):
    return login if login and not is_bot(login) else None


def needs_detail(item):
    """Whether this item justifies the extra repos/O/R/pulls/N call.

    Only bot-authored pull requests: a human opener already resolves at step 1,
    and `pulls/N` does not exist for an issue.
    """
    login = (item.get("user") or {}).get("login")
    return bool(is_bot(login) and item.get("pull_request"))


def resolve_author(item, detail=None, reviews=None, fallback=None):
    """Walk the chain. Returns (login, source); login is None if unresolved."""
    if login := _human((item.get("user") or {}).get("login")):
        return login, "opener"

    detail = detail or {}
    if login := _human((detail.get("merged_by") or {}).get("login")):
        return login, "merged_by"

    auto = (detail.get("auto_merge") or {}).get("enabled_by") or {}
    if login := _human(auto.get("login")):
        return login, "auto_merge"

    for review in reviews or []:
        # Only an approval. A comment on a PR is not ownership of it.
        if review.get("state") == "APPROVED":
            if login := _human((review.get("user") or {}).get("login")):
                return login, "approver"

    # A bot configured as the fallback defeats the point of the chain, so it is
    # treated as unset rather than honoured.
    if login := _human(fallback):
        return login, "configured"
    return None, "unresolved"


def annotate(items, details, reviews, fallback):
    """Add resolvedAuthor / authorSource to each item.

    Unresolved items are marked, never dropped — silently shrinking the sync
    would hide the problem instead of surfacing it.
    """
    out = []
    for item in items:
        num = str(item.get("number"))
        login, source = resolve_author(
            item, details.get(num), reviews.get(num), fallback
        )
        out.append({**item, "resolvedAuthor": login, "authorSource": source})
    return out


def load(path, default):
    if not path:
        return default
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--github", required=True)
    ap.add_argument("--details")
    ap.add_argument("--reviews")
    ap.add_argument("--fallback", metavar="LOGIN",
                    help="options.automationAuthor — used only when GitHub "
                         "yields no human")
    a = ap.parse_args()

    items = load(a.github, [])
    out = annotate(items, load(a.details, {}), load(a.reviews, {}), a.fallback)

    json.dump(out, sys.stdout, indent=1, ensure_ascii=False)
    print()

    w = sys.stderr.write
    counts = Counter(i["authorSource"] for i in out)
    w(f"Resolved authors for {len(out)} items\n")
    for source in ("opener", "merged_by", "auto_merge", "approver",
                   "configured", "unresolved"):
        if counts.get(source):
            w(f"  {source:<12} {counts[source]:>3}\n")

    if pending := [i["number"] for i in out if i["authorSource"] == "unresolved"]:
        # Loud on purpose. These cannot be written to the board without
        # putting a bot in the Author column, which is the one thing the
        # column may never contain.
        w(f"\n  ! no human found for {len(pending)} item(s): "
          f"{', '.join('#' + str(n) for n in pending[:10])}"
          f"{' …' if len(pending) > 10 else ''}\n")
        w("    Set options.automationAuthor to the login accountable for "
          "automation, then re-run.\n")

    if which := [i["number"] for i in items if needs_detail(i)]:
        if not a.details:
            w(f"\n  note: {len(which)} bot-authored PR(s) had no --details; "
              "steps 2-4 were skipped\n")


if __name__ == "__main__":
    main()
