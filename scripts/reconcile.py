#!/usr/bin/env python3
"""Reconcile GitHub items against a monday board and emit a sync plan.

Implements references/reconciliation.md: rebuilds identity from the board
itself, repairs state, then diffs. Read-only — it decides, it does not write.

Usage:
  reconcile.py OWNER/REPO --board board_items.json --github issues.json \
               [--state state.json] [--comments comments.json] \
               [--exclude-author LOGIN ...]

board_items.json  : get_board_items_page output (needs the GitHub URL column)
issues.json       : gh api repos/O/R/issues?state=all output
comments.json     : gh api repos/O/R/issues/comments output (optional)
state.json        : existing .monday-sync/*.json (optional; absent = first run)
--exclude-author  : skip items opened by this login (repeatable). Unioned with
                    options.excludeAuthors from state. Item-scoped: it filters
                    which issues/PRs are mirrored, not which comments post.

Emits a JSON plan on stdout and a human summary on stderr. Exit 0 always —
"nothing to do" is a valid outcome, not a failure.
"""
import argparse
import json
import re
import sys
from collections import defaultdict

from eventkeys import key_for

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


def normalize_login(login):
    """Fold a GitHub login to the form exclusions are compared in.

    Case is irrelevant, and the trailing `[bot]` on app accounts is an artefact
    of how GitHub names them rather than part of the identity a person types.
    Folding both sides means a user who configures the name they see in the UI
    gets the filter they expected instead of one that silently never matches.

    Returns "" for anything empty; "" is never a member of the exclusion set,
    so an author GitHub omitted cannot be filtered out by a blank config entry.
    """
    return re.sub(r"\[bot\]$", "", (login or "").strip().lower())


def excluded_logins(state, cli_logins):
    """The set of logins whose items this run will not mirror.

    Union of `options.excludeAuthors` in state and any --exclude-author flags.
    The flag exists for the first run, where the plan is built before a state
    file has been written and the answer still has to be expressible.
    """
    configured = (state.get("options") or {}).get("excludeAuthors") or []
    raw = [x for x in list(configured) + list(cli_logins or []) if isinstance(x, str)]
    return {n for n in (normalize_login(x) for x in raw) if n}


def item_author(src):
    """The login that opened an issue/PR, or "" when GitHub omitted it."""
    return normalize_login((src.get("user") or {}).get("login"))


def item_key(src):
    """'issue/123' or 'pr/45' for a row from the GitHub issues endpoint.

    Namespaced because a repo can have issue #45 and PR #45; the endpoint
    returns both and only the `pull_request` key tells them apart.
    """
    return ("pr/" if src.get("pull_request") else "issue/") + str(src["number"])


def comment_key(comment):
    """Event key for an issue/PR comment. Vocabulary lives in eventkeys.py."""
    return key_for("comment", gid=comment["id"])


def state_events(src):
    """Event keys for an item's terminal state transition.

    Both timestamps ride on the issues endpoint already in hand — `closed_at`,
    and `merged_at` nested inside `pull_request` for a PR — so closes and
    merges reach the feed without a single extra API call.

    Merged supersedes closed: GitHub closes a PR when it merges it, setting
    both fields to the same instant, and emitting both would post that moment
    twice. Reopening needs no case of its own — a reopened item comes back with
    `closed_at: null`, so nothing is emitted and the existing entry is not
    duplicated; closing it again yields a new key at the new timestamp.

    Keys come from `eventkeys.key_for`, the same derivation the renderer uses
    to stamp what it posts.
    """
    if merged_at := (src.get("pull_request") or {}).get("merged_at"):
        return [key_for("merged", at=merged_at)]
    if closed_at := src.get("closed_at"):
        return [key_for("closed", at=closed_at)]
    return []


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
    ap.add_argument("--exclude-author", action="append", metavar="LOGIN",
                    help="skip items opened by this login; repeatable. Merged "
                         "with options.excludeAuthors from --state.")
    a = ap.parse_args()

    repo = a.repo
    board = load(a.board) or {}
    gh = load(a.github) or []
    state = load(a.state) or {}
    comments = load(a.comments) or []
    item_map = state.get("itemMap", {})

    observed, dupes, foreign, unmanaged = board_observations(board, repo)
    excluded_authors = excluded_logins(state, a.exclude_author)

    # --- Author exclusion ------------------------------------------------
    # Item-scoped on purpose: it decides which issues and PRs are mirrored, not
    # which feed entries are posted. An excluded author commenting on somebody
    # else's issue is part of that conversation and still appears.
    excluded = []
    if excluded_authors:
        for src in gh:
            if item_author(src) in excluded_authors:
                key = item_key(src)
                excluded.append({
                    "key": key,
                    "number": src["number"],
                    "author": (src.get("user") or {}).get("login"),
                    # Non-null means the row predates the exclusion. It stays:
                    # removal is proposed to a human, never done here.
                    "mondayItemId": observed.get(key),
                })
    excluded_keys = {e["key"] for e in excluded}

    # --- Phase 1: repair state against the board -------------------------
    # An excluded item on the board is not adopted — adoption would claim it as
    # managed, and this run manages nothing it will not also keep current.
    adopted = [k for k in observed if k not in item_map and k not in excluded_keys]
    dropped = [k for k in item_map if k not in observed]

    # --- events present on GitHub, bucketed by item ----------------------
    events = defaultdict(list)
    for c in comments:
        n = str(c.get("issue_url", "")).rsplit("/", 1)[-1]
        if n.isdigit():
            events[n].append(comment_key(c))

    # --- Phase 2: diff ---------------------------------------------------
    create, update, skip = [], [], []
    for src in gh:
        num = str(src["number"])
        key = item_key(src)
        if key in excluded_keys:
            continue
        st = item_map.get(key, {})
        gh_keys = ([key_for("opened", at=src["created_at"])]
                   + events.get(num, []) + state_events(src))
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
            "unmanagedItems": unmanaged, "excluded": excluded}
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
    if excluded:
        w(f"  excluded     {len(excluded):>3}   (author in excludeAuthors)\n")
    if foreign:
        w(f"  ignored      {foreign:>3}   (items from a different repo)\n")
    if unmanaged:
        w(f"  untouched    {unmanaged:>3}   (no GitHub URL — not ours)\n")
    for k, ids in dupes.items():
        w(f"  ! duplicate {k}: extra monday items {ids}\n")
    # Named individually, because these are rows a human may want gone and
    # nothing here will ever take them off the board.
    for e in (x for x in excluded if x["mondayItemId"]):
        w(f"  ! {e['key']} already on the board as item {e['mondayItemId']}"
          f" — left untouched, no longer updated\n")


if __name__ == "__main__":
    main()
