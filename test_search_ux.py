"""Local checks for autocomplete and the newest-active-vacancies view."""
import unittest
from unittest.mock import patch

import web_app


class SearchUXTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_version = web_app.active_jobs_source_version()
        cls.titles = web_app.cached_active_titles(cls.source_version)
        if not cls.titles:
            raise unittest.SkipTest("No ACTIVE vacancy titles in the local snapshot")
        cls.prefix = next(title[:3] for title in cls.titles if len(title) >= 3)

    def test_autocomplete_uses_deduplicated_active_titles(self):
        suggestions = web_app.autocomplete_suggestions(self.prefix, limit=5)
        self.assertLessEqual(len(suggestions), 5)
        self.assertEqual(suggestions, web_app.autocomplete_suggestions(self.prefix.swapcase(), limit=5))
        self.assertEqual(len(self.titles), len({title.casefold() for title in self.titles}))
        for query in ("sy", "ren", "bu", "sj"):
            values = web_app.autocomplete_suggestions(query)
            self.assertLessEqual(len(values), 5)
            self.assertTrue(all(web_app.is_clean_autocomplete_title(value) for value in values))
            first_contains = next((index for index, value in enumerate(values)
                                   if not value.casefold().startswith(query)), len(values))
            self.assertTrue(all(value.casefold().startswith(query) for value in values[:first_contains]))
        self.assertEqual(web_app.autocomplete_suggestions("x"), [])
        self.assertEqual(web_app.autocomplete_suggestions("zzzznotajob"), [])

    def test_autocomplete_handles_norwegian_letters(self):
        o_slash, a_ring = chr(0x00f8), chr(0x00c5)
        cleaner, farm_worker = "S" + o_slash + "ppelkj" + o_slash + "rer", a_ring + "kerarbeider"
        with patch("web_app.cached_autocomplete_titles", return_value=(cleaner, farm_worker, "Renholder")):
            self.assertEqual(web_app.autocomplete_suggestions("s" + o_slash), [cleaner])
            self.assertEqual(web_app.autocomplete_suggestions(a_ring.casefold() + "k"), [farm_worker])

    def test_all_jobs_are_active_newest_first_and_paginated(self):
        rows, total, county = web_app.all_active_vacancies(page=1)
        self.assertEqual(county, "")
        self.assertEqual(len(rows), min(total, web_app.ALL_JOBS_PAGE_SIZE))
        dates = [row[3] for row in rows if row[3] is not None]
        self.assertEqual(dates, sorted(dates, reverse=True))
        next_rows, _, _ = web_app.all_active_vacancies(page=2)
        self.assertFalse({row[0] for row in rows} & {row[0] for row in next_rows})

    def test_canonical_fylke_filter_has_no_cross_region_rows(self):
        for requested in ("OSLO", "AGDER", "ROGALAND"):
            rows, _, county = web_app.all_active_vacancies(requested)
            self.assertEqual(county, requested.title())
            self.assertTrue(all(
                any((location.get("county") or "").casefold() == county.casefold() for location in locations)
                for _, _, locations, _ in rows
            ))

    def test_active_municipality_index_uses_city_fallback_and_deduplicates(self):
        jobs = {
            "one": {"workLocations": [
                {"municipal": "Kristiansand"}, {"municipal": "kristiansand"},
                {"city": " Oslo "}, {"municipal": "", "city": "Bergen"},
            ]},
            "two": {"workLocations": [{"municipal": "TROMSØ"}]},
        }
        web_app.cached_active_municipalities.cache_clear()
        try:
            with patch("web_app.cached_active_jobs", return_value=jobs):
                self.assertEqual(
                    web_app.cached_active_municipalities("municipality-test"),
                    ("Bergen", "Kristiansand", "Oslo", "Tromsø"),
                )
        finally:
            web_app.cached_active_municipalities.cache_clear()

    def test_municipality_suggestions_are_case_insensitive_prefix_first(self):
        with patch("web_app.cached_active_municipalities", return_value=(
                "Kristiansand", "Lillesand", "Sandnes")):
            self.assertEqual(web_app.municipality_suggestions("sAnD"), [
                "Sandnes", "Kristiansand", "Lillesand",
            ])
            self.assertEqual(web_app.municipality_suggestions("Kris"), ["Kristiansand"])
            self.assertEqual(web_app.municipality_suggestions("x"), [])

    def test_active_jobs_combine_profession_county_and_municipality_filters(self):
        jobs = {
            "one": {"title": "Renholder", "workLocations": [
                {"county": "Agder", "municipal": "Kristiansand"}]},
            "two": {"title": "Renholder", "workLocations": [
                {"county": "Oslo", "municipal": "Oslo"}]},
            "three": {"title": "Kokk", "workLocations": [
                {"county": "Agder", "city": "Kristiansand"}]},
            "four": {"title": "Renholder", "workLocations": [
                {"county": "Agder", "municipal": "Risør"}]},
        }
        dates = {key: index for index, key in enumerate(jobs)}
        web_app.cached_active_municipalities.cache_clear()
        try:
            with patch("web_app.active_jobs_source_version", return_value="filter-test"), \
                    patch("web_app.cached_active_jobs", return_value=jobs), \
                    patch("web_app.cached_active_published_dates", return_value=dates):
                counts = (
                    web_app.all_active_vacancies(profession="renholder")[1],
                    web_app.all_active_vacancies("AGDER")[1],
                    web_app.all_active_vacancies(municipality="KRISTIANSAND")[1],
                    web_app.all_active_vacancies(profession="renholder", municipality="Kristiansand")[1],
                    web_app.all_active_vacancies("Agder", municipality="Kristiansand")[1],
                    web_app.all_active_vacancies(
                        "Agder", profession="renholder", municipality="Kristiansand")[1],
                    web_app.all_active_vacancies(municipality="No such municipality")[1],
                )
            self.assertEqual(counts, (3, 3, 2, 1, 2, 1, 0))
        finally:
            web_app.cached_active_municipalities.cache_clear()

    def test_jobs_urls_and_detail_return_preserve_filters(self):
        from urllib.parse import parse_qs, urlsplit

        url = web_app.all_jobs_url(
            "Agder", 2, job="vacancy-1", profession="renholder", municipality="Kristiansand")
        params = parse_qs(urlsplit(url).query)
        self.assertEqual(params["q"], ["renholder"])
        self.assertEqual(params["fylke"], ["Agder"])
        self.assertEqual(params["kommune"], ["Kristiansand"])
        self.assertEqual(params["job"], ["vacancy-1"])
        with patch("web_app.job_detail", return_value="detail") as job_detail:
            web_app.all_jobs_detail(
                "vacancy-1", "Agder", 2, profession="renholder", municipality="Kristiansand")
        return_url = job_detail.call_args.kwargs["return_url"]
        return_params = parse_qs(urlsplit(return_url).query)
        self.assertEqual(return_params["q"], ["renholder"])
        self.assertEqual(return_params["kommune"], ["Kristiansand"])

    def test_rendered_jobs_form_pagination_and_detail_keep_filters(self):
        from html import unescape
        from urllib.parse import parse_qs, urlsplit

        row = ("vacancy-1", {
            "title": "Renholder", "workLocations": [{"county": "Agder", "municipal": "Kristiansand"}],
        }, [{"county": "Agder", "municipal": "Kristiansand"}], 1)
        params = {"mode": ["jobs"], "q": ["renholder"], "fylke": ["Agder"],
                  "kommune": ["Kristiansand"]}
        with patch("web_app.all_active_vacancies", return_value=([row], 50, "Agder")), \
                patch("web_app.active_county_leaders", return_value=()):
            document = web_app.render_all_jobs(
                "Agder", page=2, params=params, profession="renholder", municipality="Kristiansand")

        self.assertIn('name="q" data-autocomplete', document)
        self.assertIn('name="kommune" data-autocomplete="municipality"', document)
        self.assertIn('placeholder="Skriv kommune" value="Kristiansand"', document)
        self.assertIn('value="renholder"', document)
        hrefs = [unescape(value) for value in __import__("re").findall(r'href="([^"]+)"', document)]
        page_three = next(url for url in hrefs if "page=3" in url)
        next_params = parse_qs(urlsplit(page_three).query)
        self.assertEqual(next_params["q"], ["renholder"])
        self.assertEqual(next_params["fylke"], ["Agder"])
        self.assertEqual(next_params["kommune"], ["Kristiansand"])
        detail_url = next(url for url in hrefs if "job=vacancy-1" in url)
        detail_params = parse_qs(urlsplit(detail_url).query)
        self.assertEqual(detail_params["q"], ["renholder"])
        self.assertEqual(detail_params["kommune"], ["Kristiansand"])

    def test_all_jobs_does_not_invoke_profession_matching(self):
        with patch("web_app.active_matches", side_effect=AssertionError("profession matcher must not run")):
            page = web_app.all_jobs_page("Oslo")
        self.assertIn("Nye stillinger i Oslo", page)
        self.assertIn("job=", page)

    def test_normal_search_still_uses_the_existing_matcher(self):
        for query in ("renholder", "sykepleier", "butikkmedarbeider"):
            expected = web_app.find_jobs(web_app.cached_active_jobs(self.source_version), query, "oslo")
            actual, _ = web_app.active_matches(query, "Oslo")
            self.assertEqual(list(actual), list(expected))


if __name__ == "__main__":
    unittest.main()
