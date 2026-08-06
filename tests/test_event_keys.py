"""Tests for scripts/eventkeys.py — the shared event-key vocabulary.

An event key is the idempotency handle for one entry in a monday Updates feed.
`reconcile.py` decides an entry is new by key; `render-entries.py` stamps the
key that actually gets posted. If the two ever derive a key differently, the
feed either re-posts entries already on the board or silently drops new ones.

That exact failure shipped twice:

  1.8.1  reconcile never derived state:closed@ / state:merged@ at all, so
         closing an issue or merging a PR posted nothing.
  1.8.2  render-entries guessed state:comment@<at> for a comment built without
         an id — a key matching nothing, which queued 24 already-posted
         comments for a second posting.

Both were two implementations of one vocabulary. This module is the single
implementation, and `test_both_scripts_share_one_implementation` is what makes
a third instance impossible rather than merely unlikely.

Run: python3 -m unittest discover -s tests   (or pytest tests/)
"""
import unittest

from helpers import eventkeys, reconcile, render

AT = "2026-07-01T14:32:00Z"


class TestIdKeyedEvents(unittest.TestCase):
    """Events GitHub gives a stable id. The id is the identity, not the time."""

    def test_comment_uses_the_comment_prefix(self):
        self.assertEqual(eventkeys.key_for("comment", gid=445566), "comment:445566")

    def test_every_review_flavour_collapses_to_one_prefix(self):
        # Approve / request-changes / comment are one GitHub review object, so
        # they must key identically or the same review posts three times.
        for kind in ("review_approved", "review_changes", "review_comment"):
            with self.subTest(kind=kind):
                self.assertEqual(eventkeys.key_for(kind, gid=778899), "review:778899")

    def test_inline_and_commit_prefixes(self):
        self.assertEqual(eventkeys.key_for("inline_comment", gid=1), "rcomment:1")
        self.assertEqual(eventkeys.key_for("commit", gid="abc1234"), "commit:abc1234")

    def test_regression_id_keyed_event_without_an_id_raises(self):
        # Guessing a timestamp key here is what re-posted live entries in 1.8.2.
        for kind in eventkeys.ID_KEYED:
            with self.subTest(kind=kind):
                with self.assertRaises(eventkeys.MalformedEvent):
                    eventkeys.key_for(kind, at=AT)

    def test_the_timestamp_is_ignored_when_an_id_is_present(self):
        # An edited comment keeps its id and changes its time; the key must not
        # move, or every edit re-posts the comment.
        self.assertEqual(
            eventkeys.key_for("comment", at=AT, gid=1),
            eventkeys.key_for("comment", at="2099-01-01T00:00:00Z", gid=1),
        )


class TestTimestampKeyedEvents(unittest.TestCase):
    """Events GitHub gives no id. The instant is the only available identity."""

    def test_opened_is_its_own_shape(self):
        self.assertEqual(eventkeys.key_for("opened", at=AT), f"opened@{AT}")

    def test_state_transitions_share_the_state_prefix(self):
        for kind in ("closed", "merged", "reopened"):
            with self.subTest(kind=kind):
                self.assertEqual(
                    eventkeys.key_for(kind, at=AT), f"state:{kind}@{AT}"
                )

    def test_timestamp_keyed_event_without_a_timestamp_raises(self):
        # Same reasoning as the missing id: there is no identity to fall back
        # on, and inventing one produces a key that matches nothing.
        with self.assertRaises(eventkeys.MalformedEvent):
            eventkeys.key_for("closed")

    def test_unknown_kind_with_an_id_keeps_the_generic_shape(self):
        # Forward compatibility: a kind added later still gets a usable key.
        self.assertEqual(eventkeys.key_for("labeled", gid=42), "labeled:42")


class TestReviewKind(unittest.TestCase):
    """GitHub review state -> event kind. Shared vocabulary in its own right.

    reconcile needs it to derive the key; the renderer needs it to pick the
    glyph. Two mappings would drift exactly like two key derivations did.
    """

    def test_each_submitted_state_maps_to_its_kind(self):
        self.assertEqual(eventkeys.review_kind("APPROVED"), "review_approved")
        self.assertEqual(eventkeys.review_kind("CHANGES_REQUESTED"), "review_changes")
        self.assertEqual(eventkeys.review_kind("COMMENTED"), "review_comment")

    def test_state_matching_is_case_insensitive(self):
        self.assertEqual(eventkeys.review_kind("approved"), "review_approved")

    def test_pending_review_is_not_an_event(self):
        # A PENDING review has not been submitted — it is a draft visible only
        # to its author, with no submitted_at. Posting it leaks an unfinished
        # review to the whole board.
        self.assertIsNone(eventkeys.review_kind("PENDING"))
        self.assertIsNone(eventkeys.review_kind(None))

    def test_every_review_kind_keys_into_one_namespace(self):
        # Whatever the state, one GitHub review object is one entry.
        keys = {
            eventkeys.key_for(eventkeys.review_kind(s), gid=778899)
            for s in ("APPROVED", "CHANGES_REQUESTED", "COMMENTED")
        }
        self.assertEqual(keys, {"review:778899"})

    def test_unknown_state_degrades_to_a_generic_review(self):
        # DISMISSED and anything GitHub adds later still belong in the feed;
        # dropping them silently loses history.
        self.assertEqual(eventkeys.review_kind("DISMISSED"), "review_comment")
        self.assertEqual(eventkeys.review_kind("SOMETHING_NEW"), "review_comment")


class TestNoDrift(unittest.TestCase):
    """The invariant both shipped defects violated."""

    def test_both_scripts_share_one_implementation(self):
        # Identity, not equality. Two modules cannot drift from a function they
        # both import — this is the structural version of the 1.8.1 and 1.8.2
        # cross-check tests, and it cannot be satisfied by copying the logic.
        self.assertIs(render.key_for, eventkeys.key_for)
        self.assertIs(reconcile.key_for, eventkeys.key_for)
        self.assertIs(render.MalformedEvent, eventkeys.MalformedEvent)

    def test_renderer_event_key_agrees_with_the_shared_derivation(self):
        for ev, expected in (
            ({"kind": "comment", "id": 445566, "at": AT}, "comment:445566"),
            ({"kind": "opened", "at": AT}, f"opened@{AT}"),
            ({"kind": "merged", "at": AT}, f"state:merged@{AT}"),
        ):
            with self.subTest(kind=ev["kind"]):
                self.assertEqual(render.event_key(ev), expected)

    def test_reconcile_derivations_agree_with_the_shared_derivation(self):
        self.assertEqual(
            reconcile.comment_key({"id": 445566}),
            eventkeys.key_for("comment", gid=445566),
        )
        merged = {"pull_request": {"merged_at": AT}}
        self.assertEqual(
            reconcile.state_events(merged), [eventkeys.key_for("merged", at=AT)]
        )
        closed = {"closed_at": AT}
        self.assertEqual(
            reconcile.state_events(closed), [eventkeys.key_for("closed", at=AT)]
        )


if __name__ == "__main__":
    unittest.main()
