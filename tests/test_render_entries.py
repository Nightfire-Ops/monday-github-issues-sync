"""Tests for scripts/render-entries.py.

Every test named test_regression_* encodes a bug that reached a live monday
board. Those are the ones that matter: the renderer has no type checking and a
silent formatting regression is invisible until a PM reads the feed.

Run: python3 -m unittest discover -s tests   (or pytest tests/)
"""
import re
import unittest

from helpers import REPO, event, html_for, render


def footer_links(html):
    """Every 'View on GitHub' / 'Read the full ...' anchor label in the body."""
    return re.findall(r">(View on GitHub →|Read the full \w+ on GitHub →)</a>", html)


def self_links(html, url):
    """How many anchors point at the entry's own GitHub URL.

    This is the invariant that matters and it is wording-independent: a second
    link back to the same place is the defect, whatever its label. Matching on
    label text alone let a reworded duplicate through.
    """
    return len(re.findall(re.escape(f'href="{url}"'), html))


class TestAttribution(unittest.TestCase):
    def test_plain_login_is_unchanged(self):
        self.assertEqual(render.display_author("alice"), "alice")

    def test_regression_a_bot_identity_is_never_displayed(self):
        # This inverts the pre-1.8.0 rule, which stripped the suffix and
        # shipped "dependabot" as the author. The Author column names a person;
        # a bot has no human behind it, so unattributable is an error, not a
        # value to display.
        with self.assertRaises(render.UnresolvedAuthor):
            render.display_author("dependabot[bot]")

    def test_a_login_merely_containing_bot_survives(self):
        # A substring test here would reassign a real person's work.
        self.assertEqual(render.display_author("robotics"), "robotics")
        self.assertEqual(render.display_author("botany"), "botany")

    def test_automation_author_attributes_bot_authors(self):
        self.assertEqual(
            render.display_author("dependabot[bot]", "maintainer"), "maintainer"
        )

    def test_a_bot_automation_author_is_refused(self):
        # Attributing one bot to another satisfies the letter of the rule and
        # none of its point.
        with self.assertRaises(render.UnresolvedAuthor):
            render.display_author("dependabot[bot]", "other[bot]")

    def test_automation_author_does_not_touch_humans(self):
        # The override is scoped to [bot] authors. Re-attributing a real
        # person's comment would misrepresent who said it.
        self.assertEqual(render.display_author("alice", "maintainer"), "alice")

    def test_none_login_does_not_raise(self):
        self.assertEqual(render.display_author(None), "")

    def test_rendered_body_shows_the_human_not_the_service(self):
        html = html_for(author="dependabot[bot]", automation_author="maintainer")
        self.assertNotIn("[bot]", html)
        self.assertNotIn("dependabot", html)
        self.assertIn("Comment — maintainer", html)

    def test_no_bot_marking_in_output(self):
        # Formatting must not branch on bot-ness: once attribution is resolved,
        # an entry that came from automation renders identically to one that
        # did not. No badge, glyph, suffix, or separate treatment.
        via_bot = html_for(author="dependabot[bot]", body="x",
                           automation_author="maintainer")
        direct = html_for(author="maintainer", body="x")
        self.assertEqual(via_bot, direct)


class TestTimestamps(unittest.TestCase):
    def test_formats_as_utc_minutes(self):
        self.assertEqual(
            render.fmt_ts("2026-07-01T14:32:05Z"), "2026-07-01 14:32 UTC"
        )

    def test_body_opens_with_the_github_timestamp(self):
        # monday stamps its own created_at as "now" and ignores
        # original_creation_date, so this prefix is the only authoritative time
        # in the feed.
        self.assertIn("<b>[2026-07-01 14:32 UTC]", html_for(at="2026-07-01T14:32:05Z"))


class TestMarkdownConversion(unittest.TestCase):
    def test_headings_become_bold(self):
        self.assertIn("<b>Question</b><br/>", render.md_to_html("## Question", REPO))

    def test_bullet_runs_group_into_one_list(self):
        out = render.md_to_html("- one\n- two", REPO)
        self.assertIn("<ul><li>one</li><li>two</li></ul>", out)

    def test_ordered_runs_group_into_one_list(self):
        out = render.md_to_html("1. one\n2. two", REPO)
        self.assertIn("<ol><li>one</li><li>two</li></ol>", out)

    def test_switching_list_type_closes_the_previous_list(self):
        out = render.md_to_html("- a\n1. b", REPO)
        self.assertIn("<ul><li>a</li></ul>", out)
        self.assertIn("<ol><li>b</li></ol>", out)

    def test_switching_from_ordered_to_bullet_closes_the_list(self):
        # The mirror of the previous case; both transitions must flush.
        out = render.md_to_html("1. a\n- b", REPO)
        self.assertIn("<ol><li>a</li></ol>", out)
        self.assertIn("<ul><li>b</li></ul>", out)

    def test_inline_code_and_bold(self):
        out = render.md_to_html("**bold** and `code`", REPO)
        self.assertIn("<b>bold</b>", out)
        self.assertIn("<code>code</code>", out)

    def test_fenced_block_becomes_pre(self):
        self.assertIn("<pre>", render.md_to_html("```\nx = 1\n```", REPO))

    def test_empty_body_is_labelled_not_blank(self):
        self.assertIn("(no description)", render.md_to_html("", REPO))
        self.assertIn("(no description)", render.md_to_html(None, REPO))

    def test_state_change_entries_carry_no_missing_body_placeholder(self):
        # A close or a merge has no body by nature, so "(no description)"
        # reports an absence that was never possible and reads as data loss.
        # An *opened* item with an empty description is the opposite case: the
        # emptiness is real and worth showing, so that placeholder stays.
        for kind in ("closed", "merged", "reopened"):
            with self.subTest(kind=kind):
                out = html_for(kind=kind, body=None)
                self.assertNotIn("(no description)", out)
        self.assertIn("(no description)", html_for(kind="opened", body=None))

    def test_regression_escapes_html_in_comment_text(self):
        # Issue comments routinely contain stack traces and generics. Unescaped,
        # they break the update body or vanish.
        out = render.md_to_html("<script>alert(1)</script> & co.", REPO)
        self.assertIn("&lt;script&gt;", out)
        self.assertIn("&amp; co.", out)
        self.assertNotIn("<script>", out)

    def test_regression_images_convert_before_links(self):
        # ![alt](url) also matches the link pattern; running links first
        # produced a malformed "![alt</a>](...)" fragment.
        out = render.md_to_html("![Badge](https://example.com/b.svg)", REPO)
        self.assertIn('<a href="https://example.com/b.svg">Badge</a>', out)
        self.assertNotIn("![", out)

    def test_regression_strips_markdown_reference_definitions(self):
        out = render.md_to_html("[//]: # (dependabot-automerge-start)", REPO)
        self.assertNotIn("[//]", out)

    def test_regression_no_nested_anchors_from_issue_refs(self):
        # "[Wayfinder map #8](url)" linkified the #8 *inside* the anchor text,
        # producing nested <a> tags that render as a broken double link.
        out = render.md_to_html("[Wayfinder map #8](https://example.com/x)", REPO)
        self.assertNotRegex(out, r"<a[^>]*>[^<]*<a")
        self.assertIn("Wayfinder map #8</a>", out)

    def test_bare_issue_refs_still_linkify(self):
        # The nested-anchor fix must not disable ordinary cross-linking.
        out = render.md_to_html("Blocked by #14 here.", REPO)
        self.assertIn(f'<a href="https://github.com/{REPO}/issues/14">#14</a>', out)

    def test_regression_upstream_changelog_refs_are_not_cross_linked(self):
        # Dependency-bump PRs quote another project's release notes inside
        # <details>. Linkifying "#408" there points at the wrong repository.
        out = render.md_to_html("<details>see #408 upstream</details>", REPO)
        self.assertNotIn("issues/408", out)


class TestFooterLink(unittest.TestCase):
    LONG = "A reasonably long line of body text. " * 90

    def test_short_body_has_exactly_one_footer_link(self):
        self.assertEqual(footer_links(html_for(body="short")), ["View on GitHub →"])

    def test_regression_truncated_body_links_to_itself_exactly_once(self):
        # truncate() used to append its own "read the full comment" link while
        # render() appended "View on GitHub →" — two links to the same URL on
        # every truncated entry. Reported from a live board.
        url = "https://github.com/OWNER/REPO/issues/1#issuecomment-1"
        html = html_for(body=self.LONG, url=url)
        self.assertEqual(self_links(html, url), 1, "entry links to itself twice")

    def test_short_body_links_to_itself_exactly_once(self):
        url = "https://github.com/OWNER/REPO/issues/1#issuecomment-1"
        self.assertEqual(self_links(html_for(body="short", url=url), url), 1)

    def test_regression_truncated_body_has_exactly_one_footer_link(self):
        links = footer_links(html_for(body=self.LONG))
        self.assertEqual(len(links), 1, f"expected 1 footer link, got {links}")

    def test_truncated_comment_label_names_a_comment(self):
        self.assertEqual(
            footer_links(html_for(kind="comment", body=self.LONG)),
            ["Read the full comment on GitHub →"],
        )

    def test_truncated_opened_label_names_a_description(self):
        self.assertEqual(
            footer_links(html_for(kind="opened", body=self.LONG)),
            ["Read the full description on GitHub →"],
        )

    def test_truncation_marks_the_cut_with_an_ellipsis(self):
        self.assertIn("…<br/>", html_for(body=self.LONG))

    def test_truncate_reports_whether_it_cut(self):
        self.assertEqual(render.truncate("short"), ("short", False))
        _, cut = render.truncate("x" * (render.MAX_BODY + 100))
        self.assertTrue(cut)

    def test_truncated_body_respects_the_cap(self):
        # Some slack for the appended ellipsis and closing markup.
        body = html_for(body=self.LONG)
        self.assertLess(len(body), render.MAX_BODY + 500)


class TestEventKeys(unittest.TestCase):
    def test_comment_key_uses_the_github_id(self):
        self.assertEqual(render.event_key({"kind": "comment", "at": "t", "id": 7}),
                         "comment:7")

    def test_review_kinds_share_the_review_namespace(self):
        for kind in ("review_approved", "review_changes", "review_comment"):
            self.assertEqual(
                render.event_key({"kind": kind, "at": "t", "id": 9}), "review:9"
            )

    def test_inline_review_comment_has_its_own_namespace(self):
        # rcomment ids come from a different endpoint and can collide with
        # conversation-comment ids.
        self.assertEqual(
            render.event_key({"kind": "inline_comment", "at": "t", "id": 9}),
            "rcomment:9",
        )

    def test_opened_key_falls_back_to_the_timestamp(self):
        self.assertEqual(
            render.event_key({"kind": "opened", "at": "2026-07-01T00:00:00Z"}),
            "opened@2026-07-01T00:00:00Z",
        )

    def test_state_change_key_embeds_the_timestamp(self):
        # close -> reopen -> close must produce three distinct keys.
        self.assertEqual(
            render.event_key({"kind": "closed", "at": "2026-07-01T00:00:00Z"}),
            "state:closed@2026-07-01T00:00:00Z",
        )


class TestBodyStructure(unittest.TestCase):
    def test_opened_entry_carries_provenance(self):
        html = html_for(kind="opened", number=123)
        self.assertIn(f"{REPO}#123", html)
        self.assertIn("Synced from", html)

    def test_comment_entry_omits_provenance(self):
        self.assertNotIn("Synced from", html_for(kind="comment"))

    def test_regression_no_html_comment_marker(self):
        # monday's sanitiser strips <!-- --> from update bodies, so a marker
        # there is dead weight that implies a recovery path which does not work.
        self.assertNotIn("<!--", html_for())

    def test_footer_href_is_the_durable_identifier(self):
        # Feed recovery parses #issuecomment-<id> out of this href, since the
        # HTML comment does not survive monday.
        url = f"https://github.com/{REPO}/issues/1#issuecomment-445566"
        self.assertIn(f'href="{url}"', html_for(url=url))

    def test_unknown_kind_does_not_raise(self):
        self.assertIn("<div>", html_for(kind="totally_unknown"))


class TestOrdering(unittest.TestCase):
    def test_events_sort_oldest_first_within_an_item(self):
        # monday stamps every update "now", so feed order is the only thing
        # making the conversation readable top to bottom.
        events = [
            event(number=1, at="2026-07-03T00:00:00Z", id=3),
            event(number=1, at="2026-07-01T00:00:00Z", id=1),
            event(number=1, at="2026-07-02T00:00:00Z", id=2),
        ]
        events.sort(key=lambda e: (e["number"], e["at"]))
        self.assertEqual([e["id"] for e in events], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()


class TestCli(unittest.TestCase):
    """Exercise main() in-process: it is the entry point SKILL.md tells the
    skill to call, so its argument handling is load-bearing."""

    def run_cli(self, argv, events):
        import contextlib
        import io
        import json
        import sys

        out = io.StringIO()
        old_argv, old_stdin = sys.argv, sys.stdin
        sys.argv = argv
        sys.stdin = io.StringIO(json.dumps(events))
        try:
            with contextlib.redirect_stdout(out):
                render.main()
        finally:
            sys.argv, sys.stdin = old_argv, old_stdin
        return json.loads(out.getvalue())

    def test_renders_and_keys_every_event(self):
        result = self.run_cli(["r", REPO], [event(kind="comment", id=5)])
        self.assertEqual(result[0]["key"], "comment:5")
        self.assertIn("<div>", result[0]["html"])

    def test_sorts_oldest_first_within_an_item(self):
        result = self.run_cli(
            ["r", REPO],
            [
                event(number=1, id=2, at="2026-07-02T00:00:00Z"),
                event(number=1, id=1, at="2026-07-01T00:00:00Z"),
            ],
        )
        self.assertEqual([e["id"] for e in result], [1, 2])

    def test_automation_author_flag_is_applied(self):
        result = self.run_cli(
            ["r", REPO, "--automation-author", "maintainer"],
            [event(author="dependabot[bot]")],
        )
        self.assertIn("maintainer", result[0]["html"])
        self.assertNotIn("dependabot", result[0]["html"])

    def test_missing_repo_argument_exits(self):
        with self.assertRaises(SystemExit):
            self.run_cli(["r"], [])

    def test_repo_without_a_slash_is_rejected(self):
        with self.assertRaises(SystemExit):
            self.run_cli(["r", "notarepo"], [])

    def test_automation_author_without_a_value_exits(self):
        with self.assertRaises(SystemExit):
            self.run_cli(["r", REPO, "--automation-author"], [])
