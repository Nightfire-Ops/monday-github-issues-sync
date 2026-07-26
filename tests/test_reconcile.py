"""Tests for scripts/reconcile.py.

Reconciliation is the safety property of the whole skill: re-running must never
duplicate a board. These cases mirror the five failure modes validated by hand
against a live board (see references/reconciliation.md), so a regression shows
up here instead of as duplicate rows in front of a PM.

Run: python3 -m unittest discover -s tests   (or pytest tests/)
"""
import json
import unittest

from helpers import board, gh_issue, reconcile, url_for

REPO = "OWNER/REPO"


def observe(*rows):
    return reconcile.board_observations(board(*rows), REPO)


class TestParseKey(unittest.TestCase):
    def test_issue_url(self):
        self.assertEqual(
            reconcile.parse_key(url_for(123)), (REPO.lower(), "issue/123")
        )

    def test_pull_url_maps_to_the_pr_namespace(self):
        # A repo can have issue #45 and PR #45; they must not collide.
        self.assertEqual(
            reconcile.parse_key(url_for(45, pr=True)), (REPO.lower(), "pr/45")
        )

    def test_url_embedded_in_a_link_cell_is_found(self):
        # monday link columns read back as "#123 - <url>".
        self.assertEqual(
            reconcile.parse_key(f"#123 - {url_for(123)}")[1], "issue/123"
        )

    def test_non_github_text_yields_nothing(self):
        self.assertEqual(reconcile.parse_key("just a note"), (None, None))

    def test_empty_cell_yields_nothing(self):
        self.assertEqual(reconcile.parse_key(None), (None, None))
        self.assertEqual(reconcile.parse_key(""), (None, None))


class TestBoardObservations(unittest.TestCase):
    def test_maps_managed_rows_to_monday_ids(self):
        observed, _, _, _ = observe((111, "#1 a", url_for(1)))
        self.assertEqual(observed, {"issue/1": "111"})

    def test_rows_without_a_github_url_are_left_alone(self):
        # Somebody's hand-created row. The sync must never claim it.
        observed, _, _, unmanaged = observe((999, "My own task", None))
        self.assertEqual(observed, {})
        self.assertEqual(unmanaged, 1)

    def test_items_from_another_repo_are_ignored(self):
        # A board can host several repos.
        observed, _, foreign, _ = observe(
            (111, "#1 mine", url_for(1)),
            (222, "#1 theirs", url_for(1, repo="Other/elsewhere")),
        )
        self.assertEqual(list(observed), ["issue/1"])
        self.assertEqual(observed["issue/1"], "111")
        self.assertEqual(foreign, 1)

    def test_duplicates_are_reported_and_the_first_is_kept(self):
        observed, dupes, _, _ = observe(
            (111, "#1 a", url_for(1)), (222, "#1 a again", url_for(1))
        )
        self.assertEqual(observed["issue/1"], "111")
        self.assertEqual(dupes, {"issue/1": ["222"]})

    def test_row_with_a_number_prefix_but_no_url_is_still_untouched(self):
        # Layer-3 identity (the "#123 " name prefix) is a diagnostic only. A row
        # whose GitHub URL was cleared must not be adopted on the strength of
        # its name — that would let a rename hijack an unrelated item.
        observed, _, _, unmanaged = observe((999, "#1 looks synced but is not", None))
        self.assertEqual(observed, {})
        self.assertEqual(unmanaged, 1)

    def test_issue_and_pr_with_the_same_number_coexist(self):
        observed, dupes, _, _ = observe(
            (111, "#45 issue", url_for(45)),
            (222, "#45 pr", url_for(45, pr=True)),
        )
        self.assertEqual(observed, {"issue/45": "111", "pr/45": "222"})
        self.assertEqual(dupes, {})


class PlanCase(unittest.TestCase):
    """End-to-end plan shape, driven through the same code path the skill uses."""

    def plan(self, board_rows, gh_rows, state=None, comments=None, extra_argv=()):
        """Run reconcile.main() in-process and return the emitted plan.

        In-process rather than via subprocess so coverage sees the real code
        path, and so a traceback surfaces here instead of as an exit code.
        """
        import contextlib
        import io
        import json
        import pathlib
        import sys
        import tempfile

        tmp = pathlib.Path(tempfile.mkdtemp())
        (tmp / "board.json").write_text(json.dumps(board(*board_rows)))
        (tmp / "gh.json").write_text(json.dumps(gh_rows))
        (tmp / "comments.json").write_text(json.dumps(comments or []))
        argv = [
            "reconcile.py", REPO,
            "--board", str(tmp / "board.json"),
            "--github", str(tmp / "gh.json"),
            "--comments", str(tmp / "comments.json"),
        ]
        if state is not None:
            (tmp / "state.json").write_text(json.dumps(state))
            argv += ["--state", str(tmp / "state.json")]
        argv += list(extra_argv)

        out, err = io.StringIO(), io.StringIO()
        old_argv = sys.argv
        sys.argv = argv
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                reconcile.main()
        finally:
            sys.argv = old_argv
        self.summary = err.getvalue()
        return json.loads(out.getvalue())

    def synced_state(self, key, monday_id, updated, events):
        return {
            "itemMap": {
                key: {
                    "mondayItemId": monday_id,
                    "updatedAt": updated,
                    "syncedEvents": events,
                }
            }
        }


class TestDiff(PlanCase):
    def test_first_run_creates_everything(self):
        plan = self.plan([], [gh_issue(1), gh_issue(2)])
        self.assertEqual(len(plan["create"]), 2)
        self.assertEqual(plan["skip"], [])

    def test_regression_second_run_creates_nothing(self):
        # The core safety property: a synced, unchanged item is skipped.
        state = self.synced_state(
            "issue/1", 111, "2026-07-01T00:00:00Z", ["opened@2026-07-01T00:00:00Z"]
        )
        plan = self.plan(
            [(111, "#1 a", url_for(1))],
            [gh_issue(1, created="2026-07-01T00:00:00Z")],
            state,
        )
        self.assertEqual(plan["create"], [])
        self.assertEqual(plan["skip"], ["issue/1"])

    def test_regression_lost_state_adopts_instead_of_duplicating(self):
        # Losing an uncommitted state file used to duplicate the whole board.
        plan = self.plan([(111, "#1 a", url_for(1))], [gh_issue(1)], state=None)
        self.assertEqual(plan["create"], [])
        self.assertEqual(plan["adopted"], ["issue/1"])

    def test_adopted_item_is_watermarked_not_replayed(self):
        # An adopted item has no event history; replaying would duplicate its
        # whole feed, so it must post nothing.
        plan = self.plan(
            [(111, "#1 a", url_for(1))],
            [gh_issue(1)],
            state=None,
            comments=[{"id": 5, "issue_url": f"https://api.github.com/repos/{REPO}/issues/1"}],
        )
        self.assertTrue(all(u["newEvents"] == 0 for u in plan["update"]))

    def test_item_deleted_in_monday_is_dropped_and_recreated(self):
        state = self.synced_state("issue/1", 111, "2026-07-01T00:00:00Z", [])
        plan = self.plan([], [gh_issue(1)], state)
        self.assertEqual(plan["dropped"], ["issue/1"])
        self.assertEqual([c["key"] for c in plan["create"]], ["issue/1"])

    def test_changed_item_is_updated_not_recreated(self):
        state = self.synced_state(
            "issue/1", 111, "2026-07-01T00:00:00Z", ["opened@2026-07-01T00:00:00Z"]
        )
        plan = self.plan(
            [(111, "#1 a", url_for(1))],
            [gh_issue(1, created="2026-07-01T00:00:00Z", updated="2026-07-09T00:00:00Z")],
            state,
        )
        self.assertEqual(plan["create"], [])
        self.assertEqual([u["key"] for u in plan["update"]], ["issue/1"])

    def test_unposted_comment_is_detected_even_when_item_is_unchanged(self):
        # updated_at can lag; an unsynced event must still be found.
        state = self.synced_state(
            "issue/1", 111, "2026-07-01T00:00:00Z", ["opened@2026-07-01T00:00:00Z"]
        )
        plan = self.plan(
            [(111, "#1 a", url_for(1))],
            [gh_issue(1, created="2026-07-01T00:00:00Z")],
            state,
            comments=[{"id": 77, "issue_url": f"https://api.github.com/repos/{REPO}/issues/1"}],
        )
        self.assertEqual(plan["skip"], [])
        self.assertEqual(plan["update"][0]["newEvents"], 1)

    def test_already_synced_comment_is_not_reposted(self):
        state = self.synced_state(
            "issue/1",
            111,
            "2026-07-01T00:00:00Z",
            ["opened@2026-07-01T00:00:00Z", "comment:77"],
        )
        plan = self.plan(
            [(111, "#1 a", url_for(1))],
            [gh_issue(1, created="2026-07-01T00:00:00Z")],
            state,
            comments=[{"id": 77, "issue_url": f"https://api.github.com/repos/{REPO}/issues/1"}],
        )
        self.assertEqual(plan["skip"], ["issue/1"])

    def test_prs_and_issues_are_planned_separately(self):
        plan = self.plan([], [gh_issue(45), gh_issue(45, pr=True)])
        self.assertEqual(
            sorted(c["key"] for c in plan["create"]), ["issue/45", "pr/45"]
        )

    def test_missing_state_file_is_treated_as_a_first_run(self):
        # A path that does not exist must not crash the run.
        self.assertIsNone(reconcile.load(None))
        self.assertIsNone(reconcile.load("/nonexistent/state.json"))

    def test_summary_reports_every_bucket(self):
        # A reconciliation that repairs silently is indistinguishable from one
        # that breaks silently.
        self.plan([(111, "#1 a", url_for(1))], [gh_issue(1)], state=None)
        for line in ("adopted", "dropped", "duplicates", "skipped",
                     "to update", "to create"):
            self.assertIn(line, self.summary)

    def test_duplicates_are_named_individually_in_the_summary(self):
        self.plan(
            [(111, "#1 a", url_for(1)), (222, "#1 dupe", url_for(1))],
            [gh_issue(1)],
            state=None,
        )
        self.assertIn("duplicate issue/1", self.summary)

    def test_summary_reports_ignored_foreign_repo_items(self):
        self.plan(
            [(111, "#1 mine", url_for(1)),
             (222, "#1 theirs", url_for(1, repo="Other/elsewhere"))],
            [gh_issue(1)],
            state=None,
        )
        self.assertIn("ignored", self.summary)

    def test_plan_never_proposes_a_deletion(self):
        # The skill has no delete path; the plan must not grow one.
        plan = self.plan(
            [(999, "Someone's own row", None)], [gh_issue(1)], state=None
        )
        # Serialised, not `in plan` — that form only inspects top-level keys and
        # would pass for a deletion proposed inside any nested value.
        for forbidden in ("delete", "archive", "remove"):
            self.assertNotIn(forbidden, json.dumps(plan).lower())
        self.assertEqual(plan["unmanagedItems"], 1)


class TestExcludeAuthors(PlanCase):
    """`options.excludeAuthors` — keep an author's items off the board.

    Motivated by a repo where 7 of 8 PRs were dependency bumps and drowned the
    human work. The filter is deliberately *item-scoped*: it decides which
    issues and PRs get mirrored, not which feed entries get posted. An excluded
    author commenting on somebody else's issue is part of that conversation and
    still appears.
    """

    def excluding(self, *logins):
        return {"options": {"excludeAuthors": list(logins)}}

    def test_no_exclusions_configured_changes_nothing(self):
        plan = self.plan([], [gh_issue(1, author="someone")], self.excluding())
        self.assertEqual([c["key"] for c in plan["create"]], ["issue/1"])
        self.assertEqual(plan["excluded"], [])

    def test_excluded_author_item_is_not_created(self):
        plan = self.plan(
            [], [gh_issue(1, author="autobumper")], self.excluding("autobumper")
        )
        self.assertEqual(plan["create"], [])
        self.assertEqual([e["key"] for e in plan["excluded"]], ["issue/1"])

    def test_other_authors_are_unaffected(self):
        plan = self.plan(
            [],
            [gh_issue(1, author="autobumper"), gh_issue(2, author="a-person")],
            self.excluding("autobumper"),
        )
        self.assertEqual([c["key"] for c in plan["create"]], ["issue/2"])

    def test_bot_suffix_is_optional_on_both_sides(self):
        # GitHub appends [bot] to app accounts. A user configuring the filter
        # types the name they see in the UI; either form must match, or the
        # filter silently does nothing and the board fills up anyway.
        bare = self.plan(
            [], [gh_issue(1, author="autobumper[bot]")], self.excluding("autobumper")
        )
        suffixed = self.plan(
            [], [gh_issue(1, author="autobumper")], self.excluding("autobumper[bot]")
        )
        self.assertEqual(bare["create"], [])
        self.assertEqual(suffixed["create"], [])

    def test_matching_is_case_insensitive(self):
        plan = self.plan(
            [], [gh_issue(1, author="AutoBumper")], self.excluding("autobumper")
        )
        self.assertEqual(plan["create"], [])

    def test_blank_entries_never_match(self):
        # A stray "" in the list must not exclude everything — least of all the
        # items whose author GitHub omitted.
        plan = self.plan(
            [],
            [gh_issue(1, author="a-person"), gh_issue(2, author=None)],
            self.excluding("", "   ", None),
        )
        self.assertEqual(sorted(c["key"] for c in plan["create"]),
                         ["issue/1", "issue/2"])
        self.assertEqual(plan["excluded"], [])

    def test_item_with_no_author_is_never_excluded(self):
        # A deleted GitHub account leaves user: null. Dropping those rows would
        # lose real history to a config value that never named them.
        plan = self.plan(
            [], [gh_issue(1, author=None)], self.excluding("autobumper")
        )
        self.assertEqual([c["key"] for c in plan["create"]], ["issue/1"])

    def test_excluded_item_already_on_board_stops_being_updated(self):
        state = self.excluding("autobumper")
        state["itemMap"] = {
            "pr/1": {"mondayItemId": 111, "updatedAt": "2026-07-01T00:00:00Z",
                     "syncedEvents": []}
        }
        plan = self.plan(
            [(111, "#1 bump", url_for(1, pr=True))],
            [gh_issue(1, pr=True, author="autobumper",
                      updated="2026-07-09T00:00:00Z")],
            state,
        )
        self.assertEqual(plan["update"], [])
        self.assertEqual(plan["skip"], [])

    def test_excluded_item_on_board_is_named_with_its_monday_id(self):
        # Exclusion never removes a row that is already there. Naming the id is
        # what lets a human decide, per the deletion policy.
        plan = self.plan(
            [(111, "#1 bump", url_for(1, pr=True))],
            [gh_issue(1, pr=True, author="autobumper")],
            self.excluding("autobumper"),
        )
        self.assertEqual(plan["excluded"][0]["mondayItemId"], "111")
        self.assertIn("already on the board", self.summary)

    def test_excluded_item_on_board_is_not_adopted_into_state(self):
        # Adoption means "this skill manages it". An excluded item is not
        # managed, so it must not appear in the repair list.
        plan = self.plan(
            [(111, "#1 bump", url_for(1, pr=True))],
            [gh_issue(1, pr=True, author="autobumper")],
            self.excluding("autobumper"),
        )
        self.assertEqual(plan["adopted"], [])

    def test_exclusion_never_proposes_a_deletion(self):
        plan = self.plan(
            [(111, "#1 bump", url_for(1, pr=True))],
            [gh_issue(1, pr=True, author="autobumper")],
            self.excluding("autobumper"),
        )
        for forbidden in ("delete", "archive", "remove"):
            self.assertNotIn(forbidden, json.dumps(plan).lower())

    def test_cli_flag_excludes_without_a_state_file(self):
        # First run: the plan is built before any state exists, so the answer to
        # "should I filter these out?" has to be expressible on the command line.
        plan = self.plan(
            [], [gh_issue(1, author="autobumper")], state=None,
            extra_argv=["--exclude-author", "autobumper"],
        )
        self.assertEqual(plan["create"], [])

    def test_cli_and_state_exclusions_are_unioned(self):
        plan = self.plan(
            [],
            [gh_issue(1, author="autobumper"), gh_issue(2, author="otherbot")],
            self.excluding("autobumper"),
            extra_argv=["--exclude-author", "otherbot"],
        )
        self.assertEqual(plan["create"], [])
        self.assertEqual(len(plan["excluded"]), 2)

    def test_summary_reports_the_excluded_count(self):
        self.plan(
            [], [gh_issue(1, author="autobumper")], self.excluding("autobumper")
        )
        self.assertIn("excluded", self.summary)


if __name__ == "__main__":
    unittest.main()
