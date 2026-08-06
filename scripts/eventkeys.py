"""The event-key vocabulary. Imported by reconcile.py and render-entries.py.

An **event key** is the idempotency handle for a single entry in a monday
Updates feed. It is stored in `syncedEvents` (see `references/state-file.md`)
and is the only thing standing between a re-run and a duplicated feed:

  - `reconcile.py` decides an entry is *new* by testing its key against state.
  - `render-entries.py` stamps the key on the entry it actually posts.

Those two answers must be identical. When they are not, the feed either
re-posts entries already on the board or silently drops ones that are missing.
Both failures shipped, from two implementations of this one vocabulary:

  1.8.1  reconcile never derived `state:closed@` / `state:merged@`, so closing
         an issue or merging a PR updated columns and posted nothing.
  1.8.2  render-entries fell back to `state:comment@<at>` for a comment built
         without an id, producing a key that matched nothing in state and
         queued 24 already-posted comments for a second posting.

Each was fixed with a test comparing the two derivations. This module removes
the need for the comparison: there is one derivation, and both scripts import
it. `tests/test_event_keys.py::test_both_scripts_share_one_implementation`
asserts that by object identity, which copying cannot satisfy.

**This file is the vocabulary's only home.** Adding an event kind means adding
it here, never re-deriving a key at a call site.

Plain stdlib, no package, no install: the scripts are run directly, and Python
puts their own directory on `sys.path`, so a sibling module imports cleanly.
"""


class MalformedEvent(Exception):
    """An event cannot be keyed — the caller built it wrong.

    Raised rather than returning a best-effort key. A wrong key is worse than
    no key: it looks valid, matches nothing in `syncedEvents`, and silently
    re-posts an entry that is already on the board. Failing the run surfaces
    the mistake while it is still cheap.
    """


# Kinds GitHub gives a stable id, mapped to their key prefix.
#
# The id *is* the identity: it survives edits, so an edited comment keeps its
# key and does not re-post. Several review flavours collapse to one prefix
# because they are one GitHub review object — keying them apart would post the
# same review up to three times.
ID_KEYED = {
    "comment": "comment",
    "review_approved": "review",
    "review_changes": "review",
    "review_comment": "review",
    "inline_comment": "rcomment",
    "commit": "commit",
}


# GitHub review state -> event kind. Shared for the same reason `key_for` is:
# reconcile needs it to derive the key, the renderer needs it to pick the glyph,
# and two copies of the mapping would drift exactly as two key derivations did.
REVIEW_KIND = {
    "APPROVED": "review_approved",
    "CHANGES_REQUESTED": "review_changes",
    "COMMENTED": "review_comment",
}


def review_kind(state):
    """Event kind for a GitHub review, or None if it is not an event.

    `PENDING` is the one state that must never reach a board: it is an
    unsubmitted draft, visible only to its author and carrying no
    `submitted_at`. Posting it publishes a review its author has not finished.

    Anything else unrecognised — `DISMISSED` today, whatever GitHub adds later
    — degrades to a generic review rather than being dropped. All three kinds
    key into `review:<id>` anyway, so an unknown state costs a glyph, never an
    entry.
    """
    if not state:
        return None
    normalized = str(state).upper()
    if normalized == "PENDING":
        return None
    return REVIEW_KIND.get(normalized, "review_comment")


def key_for(kind, at=None, gid=None):
    """The event key for one feed entry.

    `gid` is the GitHub id for kinds that have one; `at` is an ISO-8601 UTC
    instant for kinds that do not. Supplying neither for a kind that needs one
    raises `MalformedEvent` — see the class docstring for why that is not a
    fallback.

        key_for("comment", gid=445566)   -> "comment:445566"
        key_for("opened",  at=iso)       -> "opened@<iso>"
        key_for("merged",  at=iso)       -> "state:merged@<iso>"
    """
    if kind in ID_KEYED:
        if not gid:
            raise MalformedEvent(
                f"{kind} event carries no id — its key comes from the GitHub "
                f"id, not the timestamp. Include `id` when building the event."
            )
        return f"{ID_KEYED[kind]}:{gid}"

    # A kind added later that happens to carry an id still gets a stable key
    # rather than being forced onto the timestamp.
    if gid:
        return f"{kind}:{gid}"

    if not at:
        raise MalformedEvent(
            f"{kind} event carries neither an id nor a timestamp, so it cannot "
            f"be identified. Include `at` when building the event."
        )

    # `opened` is its own shape: it is the item's origin, not a transition.
    if kind == "opened":
        return f"opened@{at}"
    return f"state:{kind}@{at}"
