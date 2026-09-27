import json
import unittest

import web_app


SOURCE = "https://arbeidsplassen.nav.no/stillinger/stilling/example"


def ad(*, description="", application_url="", contacts=None, link=SOURCE, source_url=""):
    return {
        "description": description,
        "application_url": application_url,
        "contact_list_json": json.dumps(contacts or []),
        "link": link,
        "source_url": source_url,
    }


class DetailApplicationFlowTests(unittest.TestCase):
    def test_direct_application_url_is_primary(self):
        data = web_app.detail_contact_data(ad(application_url="https://employer.example/apply"))
        self.assertEqual(data["primary_link"], "https://employer.example/apply")
        self.assertIn("Søk hos arbeidsgiver", web_app.detail_action_markup(data))

    def test_explicit_application_email_is_primary(self):
        data = web_app.detail_contact_data(
            ad(description='<p>Søknad merkes med "Deltid" og sendes til apply@example.no</p>'))
        self.assertEqual(data["primary_link"], "mailto:apply@example.no")
        self.assertIn('href="mailto:apply@example.no"', web_app.detail_action_markup(data))

    def test_contact_person_fields_are_clickable(self):
        data = web_app.detail_contact_data(ad(contacts=[{
            "name": "Ola Nordmann", "title": "Daglig leder", "role": "Kontaktperson",
            "email": "ola@example.no", "phone": "+47 99 88 77 66",
        }]))
        section = web_app.detail_contact_section(data)
        self.assertIn("Ola Nordmann", section)
        self.assertIn("Daglig leder", section)
        self.assertIn('href="mailto:ola@example.no"', section)
        self.assertIn('href="tel:+4799887766"', section)

    def test_direct_url_keeps_application_email_as_alternative(self):
        data = web_app.detail_contact_data(ad(
            application_url="https://employer.example/apply",
            description="<p>Alternativt: send søknad på e-post til apply@example.no</p>",
        ))
        markup = web_app.detail_action_markup(data)
        self.assertEqual(data["primary_link"], "https://employer.example/apply")
        self.assertIn("Alternativt kan du sende søknad på e-post", markup)
        self.assertIn('href="mailto:apply@example.no"', markup)

    def test_description_contacts_are_used_when_contact_list_is_empty(self):
        data = web_app.detail_contact_data(ad(
            description="<p>Kontakt oss på info@example.no eller telefon 99 88 77 66.</p>"))
        section = web_app.detail_contact_section(data)
        self.assertIsNone(data["application_email"])
        self.assertEqual(data["primary_link"], "mailto:info@example.no")
        self.assertIn('href="mailto:info@example.no"', section)
        self.assertIn('href="tel:99887766"', section)

    def test_structured_description_contact_keeps_name_role_phone_and_email(self):
        data = web_app.detail_contact_data(ad(description=(
            "<h2>Kontaktinformasjon</h2>"
            "<p>Nanna Nordmann, Daglig leder, 99887766, nanna@example.no</p>")))
        section = web_app.detail_contact_section(data)
        self.assertIn("Nanna Nordmann", section)
        self.assertIn("Daglig leder", section)
        self.assertIn('href="mailto:nanna@example.no"', section)
        self.assertIn('href="tel:99887766"', section)

    def test_arbeidsplassen_is_link_only_fallback(self):
        data = web_app.detail_contact_data(ad())
        self.assertIsNone(data["primary_link"])
        main = web_app.detail_main_application_section(data)
        side = web_app.detail_application_section(data)
        for markup in (main, side):
            self.assertIn("Se originalannonsen på Arbeidsplassen", markup)
            self.assertNotIn("detail-primary-action", markup)
            self.assertNotIn("Søknad og flere opplysninger åpnes", markup)

    def test_superrask_application_path_is_direct(self):
        url = SOURCE + "/superrask-soknad"
        data = web_app.detail_contact_data(ad(application_url=url))
        self.assertEqual(data["application_link"], url)
        self.assertEqual(data["primary_link"], url)
        self.assertEqual(web_app.detail_primary_action(data)[0], "Søk hos arbeidsgiver →")

    def test_main_and_sidebar_share_the_same_primary_action(self):
        data = web_app.detail_contact_data(ad(application_url="https://employer.example/apply"))
        main = web_app.detail_main_application_section(data, deadline_raw="2026-10-08")
        side = web_app.detail_application_section(data)
        expected = 'href="https://employer.example/apply"'
        self.assertIn(expected, main)
        self.assertIn(expected, side)
        self.assertIn("detail-main-top", main)
        self.assertIn("Søk innen 8. oktober 2026", main)
        self.assertNotIn("detail-main-top", side)
        self.assertIn("Se originalannonsen på Arbeidsplassen", main)
        self.assertIn("Se originalannonsen på Arbeidsplassen", side)

    def test_main_application_card_uses_compact_fallback_status(self):
        data = web_app.detail_contact_data(ad(description="Send søknad til apply@example.no"))
        main = web_app.detail_main_application_section(data)
        self.assertIn("Søk snarest mulig", main)
        self.assertIn('href="mailto:apply@example.no"', main)

    def test_main_labels_contact_email_as_alternative_without_changing_sidebar(self):
        data = web_app.detail_contact_data(ad(
            application_url="https://employer.example/apply",
            contacts=[{"email": "contact@example.no"}],
        ))
        main = web_app.detail_main_application_section(data)
        side = web_app.detail_application_section(data)
        self.assertIn("Alternativt kan du sende søknad på e-post", main)
        self.assertNotIn("Alternativt kan du sende søknad på e-post", side)
        self.assertIn('href="mailto:contact@example.no"', main)
        self.assertIn('href="mailto:contact@example.no"', side)


if __name__ == "__main__":
    unittest.main()
