import json
import unittest

import nav_feed_sqlite


class ContactPipelineTests(unittest.TestCase):
    def test_parse_public_ad_html(self):
        ad = {
            "id": "example-id",
            "status": "ACTIVE",
            "application": {
                "applicationEmail": "apply@example.no",
                "applicationUrl": None,
                "hasSuperraskSoknad": True,
            },
            "contactList": [],
        }
        payload = '7:["$",{"adData":' + json.dumps(ad) + '}]'
        push = json.dumps([1, payload])
        html = '<script>self.__next_f.push(' + push + ')</script>'
        self.assertEqual(nav_feed_sqlite.parse_public_ad_html(html, "example-id"), ad)

    def test_existing_fields_receive_public_application_data(self):
        feed = {"applicationUrl": "", "contactList": [{
            "name": "Thomas", "email": None, "phone": None,
            "role": None, "title": "Daglig leder",
        }]}
        public = {
            "application": {
                "applicationEmail": "jobs@example.no",
                "applicationUrl": None,
                "hasSuperraskSoknad": True,
            },
            "contactList": feed["contactList"],
        }
        url, raw_contacts = nav_feed_sqlite.enriched_application_data(
            "example-id", feed, public,
        )
        contacts = json.loads(raw_contacts)
        self.assertEqual(
            url,
            nav_feed_sqlite.PUBLIC_JOB_URL + "example-id/superrask-soknad",
        )
        self.assertEqual(contacts[0]["email"], "jobs@example.no")
        self.assertEqual(contacts[1]["name"], "Thomas")

    def test_direct_feed_url_is_preserved(self):
        url, raw_contacts = nav_feed_sqlite.enriched_application_data(
            "example-id",
            {"applicationUrl": "https://employer.example/apply", "contactList": []},
        )
        self.assertEqual(url, "https://employer.example/apply")
        self.assertEqual(json.loads(raw_contacts), [])


if __name__ == "__main__":
    unittest.main()
