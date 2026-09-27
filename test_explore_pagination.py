"""Pagination preserves the complete Explore ranking and the user's route state."""
import io
import sqlite3
import tempfile
import unittest
from contextlib import closing
from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlencode, urlsplit

import web_app


class ExploreHTML(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.cards = 0
        self.jobs = []
        self.links = []
        self.pages = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "article" and "job-row" in attrs.get("class", "").split():
            self.cards += 1
        if tag == "a":
            params = parse_qs(urlsplit(attrs.get("href", "")).query)
            self.links.append(params)
            if "job-link" in attrs.get("class", "").split():
                self.jobs.append(params)
            if attrs.get("rel") in ("prev", "next"):
                self.pages[attrs["rel"]] = params

    @property
    def uuids(self):
        return [params["job"][0] for params in self.jobs]


class ExplorePaginationTests(unittest.TestCase):
    def setUp(self):
        self.params = {key: [value] for key, value in dict(
            mode="explore", language="b2", licence="b", experience="some",
            hours="flex", training="yes", direction="assistanse").items()}
        requirement = web_app.requirements({"description": "Opplæring vil bli gitt."})
        self.items = []
        for index in range(208):
            uid = f"vacancy-{index:03d}"
            ad = dict(uuid=uid, title=f"Personlig assistent {index}", description="Opplæring vil bli gitt.",
                      employer={"name": "Test employer"}, workLocations=[{
                          "county": "OSLO", "municipal": "Oslo" if index % 2 == 0 else "Tromsø"}])
            self.items.append((uid, ad, deepcopy(requirement), True, 0))
        self.groups = {"assistanse": self.items}
        self.candidates = self.start_patch("web_app.cached_explore_candidates", return_value=(self.groups, {}))
        self.dates = self.start_patch("web_app.explore_published_dates", return_value={})

    def start_patch(self, name, **kwargs):
        patcher = patch(name, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def render(self, **changes):
        params = dict(self.params, **{key: [str(value)] for key, value in changes.items()})
        html = web_app.explore_page(params, params.get("lang", ["no"])[0])
        return html, ExploreHTML(html)

    def test_all_pages_preserve_order_union_and_unique_cards(self):
        collected = []
        for page in range(1, 12):
            html, parsed = self.render(page=page)
            expected = [item[0] for item in self.items[(page - 1) * 20:page * 20]]
            self.assertEqual(parsed.uuids, expected)
            self.assertEqual(parsed.cards, 8 if page == 11 else 20)
            self.assertIn('class="result-count">208 annonser', html)
            self.assertIn(f"Side {page} av 11", html)
            self.assertEqual("prev" in parsed.pages, page > 1)
            self.assertEqual("next" in parsed.pages, page < 11)
            self.assertEqual(self.dates.call_args.args[0], expected)
            collected.extend(parsed.uuids)
        self.assertEqual(collected, [item[0] for item in self.items])
        self.assertEqual(len(collected), len(set(collected)))

    def test_filters_apply_before_slice_and_navigation_changes_only_page(self):
        html, parsed = self.render(page=2, sted="tromsø", lang="en", extra="kept")
        filtered = [item[0] for index, item in enumerate(self.items) if index % 2]
        self.assertEqual(parsed.uuids, filtered[20:40])
        self.assertIn('class="result-count">104 annonser', html)
        self.assertIn("104 stillinger", html)
        self.assertIn("Page 2 of 6", html)
        expected = dict(self.params, sted=["tromsø"], lang=["en"], extra=["kept"])
        self.assertEqual(parsed.pages["prev"], dict(expected, page=["1"]))
        self.assertEqual(parsed.pages["next"], dict(expected, page=["3"]))
        self.assertEqual(parsed.jobs[0], dict(expected, page=["2"], job=[filtered[20]]))

    def test_detail_return_keeps_page_and_all_filters(self):
        _, parsed = self.render(page=4, sted="Oslo", lang="en")
        params = parsed.jobs[0]
        with patch("web_app.job_detail", return_value="<section>Vacancy content</section>") as detail:
            web_app.explore_page(params, "en")
        returned = parse_qs(urlsplit(detail.call_args.kwargs["return_url"]).query)
        expected = {key: value for key, value in params.items() if key != "job"}
        self.assertEqual(returned, expected)
        self.assertEqual(returned["page"], ["4"])
        page = ExploreHTML(web_app.explore_page(returned, "en"))
        self.assertEqual(page.uuids, parsed.uuids)

    def test_repeated_query_parameters_keep_the_active_first_value(self):
        params = dict(self.params, sted=["Oslo", "Tromsø"], language=["b2", "basic"], page=["1"])
        parsed = ExploreHTML(web_app.explore_page(params))
        self.assertEqual(parsed.pages["next"], dict(params, page=["2"]))
        next_page = ExploreHTML(web_app.explore_page(parsed.pages["next"]))
        expected = [item[0] for index, item in enumerate(self.items) if index % 2 == 0][20:40]
        self.assertEqual(next_page.uuids, expected)

    def test_invalid_pages_are_safe_through_http_handler(self):
        for value in (None, "", "bad", "1.5", "0", "-2", "9" * 5000, "9999"):
            with self.subTest(page=value):
                params = dict(self.params)
                if value is not None:
                    params["page"] = [value]
                handler = web_app.Handler.__new__(web_app.Handler)
                handler.path = "/?" + urlencode(params, doseq=True)
                handler.headers = {}
                handler.wfile = io.BytesIO()
                handler.send_response = Mock()
                handler.send_header = Mock()
                handler.end_headers = Mock()
                handler.do_GET()
                handler.send_response.assert_called_once_with(200)
                parsed = ExploreHTML(handler.wfile.getvalue().decode("utf-8"))
                expected = self.items[200:] if value == "9999" else self.items[:20]
                self.assertEqual(parsed.uuids, [item[0] for item in expected])

    def test_empty_group_has_no_cards_or_out_of_range_links(self):
        self.candidates.return_value = ({"assistanse": []}, {})
        html, parsed = self.render(page=30)
        self.assertEqual(parsed.cards, 0)
        self.assertEqual(parsed.pages, {})
        self.assertIn('class="result-count">0 annonser', html)
        self.dates.assert_called_once_with([])

    def test_changing_place_resets_page(self):
        _, parsed = self.render(page=4, sted="Oslo")
        other_place = [params for params in parsed.links if params.get("sted") == ["Tromsø"]]
        self.assertTrue(other_place)
        self.assertTrue(all("page" not in params and "job" not in params for params in other_place))

    def test_question_form_does_not_run_matching_or_dates(self):
        page = web_app.explore_page({"mode": ["explore"], "page": ["2"]})
        self.assertIn('class="explore-form"', page)
        self.candidates.assert_not_called()
        self.dates.assert_not_called()


class ExplorePublishedDatesTests(unittest.TestCase):
    def test_only_requested_current_active_versions_are_returned(self):
        with tempfile.TemporaryDirectory(prefix="explore-dates-test-") as directory:
            database = Path(directory) / "dates.db"
            with closing(sqlite3.connect(database)) as db, db:
                db.executescript("""
                    CREATE TABLE jobs(uuid TEXT PRIMARY KEY, status TEXT, current_version_id INTEGER);
                    CREATE TABLE job_versions(id INTEGER PRIMARY KEY, job_uuid TEXT, status TEXT, published INTEGER);
                    INSERT INTO jobs VALUES ('a','ACTIVE',1),('b','ACTIVE',2),('inactive','INACTIVE',3),
                                            ('inactive-version','ACTIVE',4),('wrong-version','ACTIVE',5);
                    INSERT INTO job_versions VALUES (1,'a','ACTIVE',100),(2,'b','ACTIVE',200),
                        (3,'inactive','ACTIVE',300),(4,'inactive-version','INACTIVE',400),
                        (5,'different-uuid','ACTIVE',500),(6,'a','ACTIVE',600);
                """)
            with patch("web_app.DATABASE", database):
                dates = web_app.explore_published_dates(["a", "a", "missing", "inactive", "inactive-version", "wrong-version"])
                self.assertEqual(dates, {"a": 100})
                self.assertEqual(web_app.explore_published_dates(["b"]), {"b": 200})

    def test_empty_page_does_not_open_database(self):
        with patch("web_app.sqlite3.connect", side_effect=AssertionError("Empty page opened database")):
            self.assertEqual(web_app.explore_published_dates([]), {})


if __name__ == "__main__":
    unittest.main()
