from django.conf import settings
from wagtail.models import Page, Site

from core.trust_pages import TRUST_PAGE_SLUGS


def site_navigation(request):
    """Sections for the masthead nav and footer, plus the live About/policy pages.

    `trust_pages` maps a key (about, ai_policy, corrections, contact,
    grievances, terms, privacy) to the live page; unpublished ones are absent.
    """
    site = Site.find_for_request(request)
    if site is None:
        return {"nav_sections": [], "about_page": None, "trust_pages": {}, "site_base_url": settings.SITE_BASE_URL}

    from news.models import SectionPage

    root = site.root_page
    sections = list(SectionPage.objects.child_of(root).live().in_menu())
    keys = {slug: key for key, slug in TRUST_PAGE_SLUGS.items()}
    trust_pages = {
        keys[page.slug]: page
        for page in Page.objects.child_of(root).live().filter(slug__in=keys)
    }
    return {
        "nav_sections": sections,
        "about_page": trust_pages.get("about"),
        "trust_pages": trust_pages,
        "site_base_url": settings.SITE_BASE_URL,
    }
