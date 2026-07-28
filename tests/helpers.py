"""Load the skill's scripts as importable modules.

The scripts are named with hyphens (`render-entries.py`) because they are run
directly, so they cannot be imported normally. This resolves them by path,
which also means the tests exercise the exact files that ship — not a copy.
"""
import importlib.util
import pathlib
import sys

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "scripts"


def load(filename, name):
    path = SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


render = load("render-entries.py", "render_entries")
reconcile = load("reconcile.py", "reconcile_mod")
resolve = load("resolve-authors.py", "resolve_authors")

REPO = "OWNER/REPO"


def event(kind="comment", number=1, body="text", **kw):
    """Build an event dict with sane defaults, plus its computed key.

    Id-keyed kinds get a default `id`: their key is derived from the GitHub id,
    so an event built without one is malformed and the renderer now rejects it.
    """
    ev = {
        "kind": kind,
        "number": number,
        "at": kw.pop("at", "2026-07-01T14:32:00Z"),
        "author": kw.pop("author", "someone"),
        "body": body,
        "url": kw.pop("url", f"https://github.com/{REPO}/issues/{number}"),
    }
    if kind in render.ID_KEYED:
        ev["id"] = kw.pop("id", 445566)
    ev.update(kw)
    ev["key"] = render.event_key(ev)
    return ev


def html_for(**kw):
    """Render a single event to its monday update body."""
    automation = kw.pop("automation_author", None)
    return render.render(event(**kw), REPO, automation)


def board(*rows):
    """Build a get_board_items_page-shaped payload.

    Each row is (monday_id, name, github_url_or_None).
    """
    return {
        "items": [
            {"id": str(i), "name": n, "column_values": {"link_col": u}}
            for i, n, u in rows
        ]
    }


def gh_issue(number, pr=False, updated="2026-07-01T00:00:00Z", **kw):
    """Build a GitHub issues-endpoint row.

    `author` is a convenience for the nested `user.login` the API returns; pass
    `author=None` to model a row whose author GitHub omitted (deleted account).
    """
    author = kw.pop("author", "someone")
    merged = kw.pop("merged", None)
    row = {
        "number": number,
        "created_at": kw.pop("created", "2026-07-01T00:00:00Z"),
        "updated_at": updated,
        "state": kw.pop("state", "open"),
        "user": {"login": author} if author is not None else None,
    }
    if pr:
        # merged_at rides inside `pull_request` on the issues endpoint — the
        # top-level `merged_at` only exists on the pulls endpoint.
        row["pull_request"] = {"url": "x"}
        if merged is not None:
            row["pull_request"]["merged_at"] = merged
    row.update(kw)
    return row


def url_for(number, pr=False, repo="OWNER/REPO"):
    kind = "pull" if pr else "issues"
    return f"https://github.com/{repo}/{kind}/{number}"
