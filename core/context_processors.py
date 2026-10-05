from django.conf import settings
from wagtail.models import Site

from core.newsroom import ABOUT_SLUG


def site_navigation(request):
    """Sections for the masthead nav and footer, plus the About page."""
    site = Site.find_for_request(request)
    if site is None:
        return {"nav_sections": [], "about_page": None, "site_base_url": settings.SITE_BASE_URL}

    from news.models import SectionPage
    from core.models import StandardPage

    root = site.root_page
    sections = list(SectionPage.objects.child_of(root).live().in_menu())
    about = StandardPage.objects.child_of(root).live().filter(slug=ABOUT_SLUG).first()
    return {
        "nav_sections": sections,
        "about_page": about,
        "site_base_url": settings.SITE_BASE_URL,
    }
