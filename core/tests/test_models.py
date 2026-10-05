from wagtail.models import Site
from wagtail.test.utils import WagtailPageTestCase

from core.models import SiteSettings, StandardPage
from news.models import HomePage
from news.tests.utils import make_home


class StandardPageTests(WagtailPageTestCase):
    def test_parents(self):
        self.assertAllowedParentPageTypes(StandardPage, {HomePage, StandardPage})

    def test_create(self):
        home = make_home()
        page = home.add_child(
            instance=StandardPage(
                title="About & AI policy",
                slug="about",
                intro="Who we are.",
                body=[{"type": "heading", "value": "Our AI policy"}],
            )
        )
        self.assertEqual(page.url_path, "/ledger-home/about/")


class SiteSettingsTests(WagtailPageTestCase):
    def test_defaults(self):
        make_home()
        settings = SiteSettings.for_site(Site.objects.get(is_default_site=True))
        self.assertEqual(settings.site_name, "The Ledger")
        self.assertEqual(settings.publication_language, "en")
