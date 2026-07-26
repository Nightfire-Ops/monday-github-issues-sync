"""Tests for scripts/resolve-authors.py.

The rule this enforces: the Author column names a person, never a bot. A
`[bot]` identity is not an author — nobody's account pushed it — so the
resolver walks GitHub for a human who actually touched the item and only falls
back to configuration when GitHub can prove nobody did.

Verified against a live repo: seven open dependabot PRs had merged_by,
auto_merge.enabled_by, and reviews all null, which is exactly the case the
fallback exists for.

Run: python3 -m unittest discover -s tests
"""
import unittest

from helpers import resolve


def item(author="a-person", number=1, pr=True):
    row = {"number": number, "user": {"login": author} if author else None}
    if pr:
        row["pull_request"] = {"url": "x"}
    return row


def detail(merged_by=None, auto_merge_by=None):
    return {
        "merged_by": {"login": merged_by} if merged_by else None,
        "auto_merge": {"enabled_by": {"login": auto_merge_by}} if auto_merge_by
        else None,
    }


def reviews(*pairs):
    return [{"user": {"login": u}, "state": s} for u, s in pairs]


class TestIsBot(unittest.TestCase):
    def test_bot_suffix_is_the_signal(self):
        self.assertTrue(resolve.is_bot("dependabot[bot]"))
        self.assertFalse(resolve.is_bot("dependabot"))

    def test_a_name_containing_bot_is_not_a_bot(self):
        # "robotics" must not trip a substring match.
        self.assertFalse(resolve.is_bot("robotics"))
        self.assertFalse(resolve.is_bot("botany"))

    def test_missing_login_is_not_a_bot(self):
        self.assertFalse(resolve.is_bot(None))
        self.assertFalse(resolve.is_bot(""))


class TestChain(unittest.TestCase):
    def resolve(self, *a, **kw):
        return resolve.resolve_author(*a, **kw)

    def test_human_opener_wins_immediately(self):
        # The common case, and the reason most installs need no configuration:
        # work pushed through a harness is authored by the human's account.
        login, source = self.resolve(item(author="a-person"))
        self.assertEqual((login, source), ("a-person", "opener"))

    def test_human_opener_does_not_need_any_github_detail(self):
        # Step 1 must not require the extra pulls/N call.
        login, source = self.resolve(item(author="a-person"), detail=None)
        self.assertEqual(source, "opener")

    def test_bot_opener_falls_through_to_merged_by(self):
        login, source = self.resolve(
            item(author="depbot[bot]"), detail=detail(merged_by="a-person")
        )
        self.assertEqual((login, source), ("a-person", "merged_by"))

    def test_bot_merger_is_skipped_for_the_human_who_enabled_auto_merge(self):
        # GitHub records github-actions[bot] as the merger when auto-merge
        # fires; the human is the one who turned it on.
        login, source = self.resolve(
            item(author="depbot[bot]"),
            detail=detail(merged_by="github-actions[bot]",
                          auto_merge_by="a-person"),
        )
        self.assertEqual((login, source), ("a-person", "auto_merge"))

    def test_falls_through_to_the_first_human_approver(self):
        login, source = self.resolve(
            item(author="depbot[bot]"),
            detail=detail(),
            reviews=reviews(("depbot[bot]", "APPROVED"),
                            ("a-person", "APPROVED")),
        )
        self.assertEqual((login, source), ("a-person", "approver"))

    def test_a_non_approving_review_does_not_count(self):
        # Commenting on a PR is not owning it.
        login, source = self.resolve(
            item(author="depbot[bot]"),
            detail=detail(),
            reviews=reviews(("a-person", "COMMENTED")),
            fallback="fallback-person",
        )
        self.assertEqual((login, source), ("fallback-person", "configured"))

    def test_configured_fallback_is_the_last_resort(self):
        # The live case: an open, unmerged, unreviewed bot PR. Every GitHub
        # signal is null because no human has touched it.
        login, source = self.resolve(
            item(author="depbot[bot]"), detail=detail(), reviews=[],
            fallback="fallback-person",
        )
        self.assertEqual((login, source), ("fallback-person", "configured"))

    def test_unresolvable_returns_none_rather_than_a_bot(self):
        # The invariant: when nothing yields a human, the answer is "no
        # answer". Returning the bot login would put it on the board, which is
        # the exact thing this module exists to prevent.
        login, source = self.resolve(item(author="depbot[bot]"), detail=detail())
        self.assertIsNone(login)
        self.assertEqual(source, "unresolved")

    def test_a_bot_is_never_returned_from_any_step(self):
        # Belt and braces across the whole chain: no configuration, every
        # signal a bot. Nothing may leak through.
        login, _ = self.resolve(
            item(author="depbot[bot]"),
            detail=detail(merged_by="ci[bot]", auto_merge_by="other[bot]"),
            reviews=reviews(("reviewer[bot]", "APPROVED")),
            fallback=None,
        )
        self.assertIsNone(login)

    def test_a_bot_fallback_is_refused(self):
        # Configuring a bot as the fallback defeats the point; treat it as
        # unset rather than honouring it.
        login, source = self.resolve(
            item(author="depbot[bot]"), detail=detail(), fallback="other[bot]"
        )
        self.assertIsNone(login)
        self.assertEqual(source, "unresolved")

    def test_missing_user_object_does_not_crash(self):
        # GitHub returns user: null for deleted accounts.
        login, source = self.resolve(item(author=None), fallback="a-person")
        self.assertEqual((login, source), ("a-person", "configured"))


class TestNeedsDetail(unittest.TestCase):
    """Which items justify the extra pulls/N call."""

    def test_human_authored_items_need_no_extra_call(self):
        self.assertFalse(resolve.needs_detail(item(author="a-person")))

    def test_bot_authored_items_do(self):
        self.assertTrue(resolve.needs_detail(item(author="depbot[bot]")))

    def test_bot_authored_issues_do_not(self):
        # pulls/N does not exist for an issue; there is nothing to fetch.
        self.assertFalse(
            resolve.needs_detail(item(author="depbot[bot]", pr=False))
        )


class TestAnnotate(unittest.TestCase):
    """The CLI's payload transform, exercised directly."""

    def test_every_item_gains_a_resolved_author_and_source(self):
        out = resolve.annotate([item(author="a-person", number=1)], {}, {}, None)
        self.assertEqual(out[0]["resolvedAuthor"], "a-person")
        self.assertEqual(out[0]["authorSource"], "opener")

    def test_details_are_keyed_by_item_number(self):
        out = resolve.annotate(
            [item(author="depbot[bot]", number=7)],
            {"7": detail(merged_by="a-person")}, {}, None,
        )
        self.assertEqual(out[0]["resolvedAuthor"], "a-person")

    def test_unresolved_items_are_marked_not_dropped(self):
        # Dropping them would silently shrink the sync. They must surface.
        out = resolve.annotate([item(author="depbot[bot]", number=1)], {}, {}, None)
        self.assertIsNone(out[0]["resolvedAuthor"])
        self.assertEqual(out[0]["authorSource"], "unresolved")


if __name__ == "__main__":
    unittest.main()
