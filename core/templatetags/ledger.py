from django import template
from django.conf import settings

register = template.Library()


@register.filter
def absolute(url):
    """Turn a site-relative URL into an absolute one on the canonical origin."""
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    return settings.SITE_BASE_URL + (url if url.startswith("/") else "/" + url)


@register.simple_tag(takes_context=True)
def is_active_section(context, section):
    page = context.get("page") or context.get("self")
    if page is None:
        return False
    return page.path.startswith(section.path)


@register.filter
def join_authors(authors):
    names = [a.name for a in authors]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _site_name(context):
    from core.models import SiteSettings

    request = context.get("request")
    return SiteSettings.for_request(request).site_name if request else "The Ledger"


@register.simple_tag(takes_context=True)
def article_json_ld(context, page):
    from news.seo import article_json_ld as build, to_json_ld

    return to_json_ld(build(page, _site_name(context)))


@register.simple_tag(takes_context=True)
def website_json_ld(context):
    from django.urls import reverse

    from news.seo import to_json_ld, website_json_ld as build

    return to_json_ld(build(_site_name(context), reverse("news:search")))


@register.simple_tag
def share_image_url(image):
    """Absolute URL of a 1200x630 Open Graph rendition, or '' without an image."""
    if not image:
        return ""
    return absolute(image.get_rendition("fill-1200x630").url)
