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
