#!/usr/bin/env python3
"""Reconcile GitHub items against a monday board and emit a sync plan.

Implements references/reconciliation.md: rebuilds identity from the board
itself, repairs state, then diffs. Read-only — it decides, it does not write.

Usage:
  reconcile.py OWNER/REPO --board board_items.json --github issues.json \
               [--state state.json] [--comments comments.json]

board_items.json  : get_board_items_page output (needs the GitHub URL column)
issues.json       : gh api repos/O/R/issues?state=all output
comments.json     : gh api repos/O/R/issues/comments output (optional)
state.json        : existing .monday-sync/*.json (optional; absent = first run)

Emits a JSON plan on stdout and a human summary on stderr. Exit 0 always —
"nothing to do" is a valid outcome, not a failure.
"""
import argparse
import json
import re
import sys
from collections import defaultdict

URL_RE = re.compile(
    r"github\.com/([^/\s]+)/([^/\s]+)/(issues|pull)/(\d+)", re.I
)


def parse_key(text):
    """Extract ('owner/repo', 'issue/123') from any GitHub URL in a cell."""
    if not text:
        return None, None
    m = URL_RE.search(str(text))
    if not m:
        return None, None
    owner, repo, kind, num = m.groups()
    return f"{owner}/{repo}".lower(), f"{'pr' if kind == 'pull' else 'issue'}/{num}"


def load(path):
    if not path:
        return None
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None


def board_observations(board, repo):
    """Layer 2/3 identity: what the board says actually exists."""
    items = board.get("items", board) if isinstance(board, dict) else board
    observed, dupes, foreign, unmanaged = {}, defaultdict(list), 0, 0
    for it in items:
        cells = it.get("column_values", {}) or {}
        slug = key = None
        for v in cells.values():
            slug, key = parse_key(v)
            if key:
                break
        if not key:                                  # human row, or placeholder
            if m := re.match(r"^#(\d+)\s", it.get("name", "")):
                unmanaged += 1                       # name-prefix only: layer 3
            else:
                unmanaged += 1
            continue
        if slug != repo.lower():
            foreign += 1                             # another repo on this board
            continue
        if key in observed:
            dupes[key].append(it["id"])
        else:
            observed[key] = str(it["id"])
    return observed, dict(dupes), foreign, unmanaged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--board", required=True)
    ap.add_argument("--github", required=True)
    ap.add_argument("--state")
    ap.add_argument("--comments")
    a = ap.parse_args()

    repo = a.repo
    board = load(a.board) or {}
    gh = load(a.github) or []
    state = load(a.state) or {}
    comments = load(a.comments) or []
    item_map = state.get("itemMap", {})

    observed, dupes, foreign, unmanaged = board_observations(board, repo)

    # --- Phase 1: repair state against the board -------------------------
    adopted = [k for k in observed if k not in item_map]
    dropped = [k for k in item_map if k not in observed]

    # --- events present on GitHub, bucketed by item ----------------------
    events = defaultdict(list)
    for c in comments:
        n = str(c.get("issue_url", "")).rsplit("/", 1)[-1]
        if n.isdigit():
            events[n].append(f"comment:{c['id']}")

    # --- Phase 2: diff ---------------------------------------------------
    create, update, skip = [], [], []
    for src in gh:
        num = str(src["number"])
        key = ("pr/" if src.get("pull_request") else "issue/") + num
        st = item_map.get(key, {})
        gh_keys = [f"opened@{src['created_at']}"] + events.get(num, [])
        synced = set(st.get("syncedEvents", []))
        new_events = [k for k in gh_keys if k not in synced]

        if key not in observed:
            create.append({"key": key, "number": src["number"],
                           "events": len(gh_keys)})
        elif not st:
            # adopted with no history: watermark, never replay (see docs)
            update.append({"key": key, "mondayItemId": observed[key],
                           "reason": "adopted — watermark only, no backfill",
                           "newEvents": 0})
        elif src["updated_at"] > st.get("updatedAt", ""):
            update.append({"key": key, "mondayItemId": observed[key],
                           "reason": "changed since last sync",
                           "newEvents": len(new_events)})
        elif new_events:
            update.append({"key": key, "mondayItemId": observed[key],
                           "reason": "unposted events", "newEvents": len(new_events)})
        else:
            skip.append(key)

    plan = {"repo": repo, "create": create, "update": update,
            "skip": skip, "adopted": adopted, "dropped": dropped,
            "duplicates": dupes, "foreignRepoItems": foreign,
            "unmanagedItems": unmanaged}
    json.dump(plan, sys.stdout, indent=1)
    print()

    w = sys.stderr.write
    w(f"Reconciled {len(observed)} board items against {len(gh)} GitHub items\n")
    w(f"  adopted      {len(adopted):>3}   (on board, missing from state)\n")
    w(f"  dropped      {len(dropped):>3}   (in state, no longer on board)\n")
    w(f"  duplicates   {len(dupes):>3}\n")
    w(f"  skipped      {len(skip):>3}   (unchanged since last sync)\n")
    w(f"  to update    {len(update):>3}\n")
    w(f"  to create    {len(create):>3}\n")
    if foreign:
        w(f"  ignored      {foreign:>3}   (items from a different repo)\n")
    if unmanaged:
        w(f"  untouched    {unmanaged:>3}   (no GitHub URL — not ours)\n")
    for k, ids in dupes.items():
        w(f"  ! duplicate {k}: extra monday items {ids}\n")


if __name__ == "__main__":
    main()
