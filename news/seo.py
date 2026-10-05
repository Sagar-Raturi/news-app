"""Structured data (schema.org JSON-LD) builders."""

import json

from django.templatetags.static import static
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.safestring import mark_safe

from core.templatetags.ledger import absolute

# Google requires 16x9, 4x3 and 1x1 images of at least 1200px wide for best results.
IMAGE_SPECS = ["fill-1200x675", "fill-1200x900", "fill-1200x1200"]
EDITORIAL_BOARD_SLUG = "editorial-board"


def to_json_ld(data):
    """Serialise for a <script type="application/ld+json"> block safely."""
    text = json.dumps(data, ensure_ascii=False, indent=None)
    text = text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return mark_safe(text)


def publisher(site_name):
    return {
        "@type": "NewsMediaOrganization",
        "name": site_name,
        "url": absolute("/"),
        "logo": {
            "@type": "ImageObject",
            "url": absolute(static("img/logo.png")),
            "width": 600,
            "height": 60,
        },
    }


def author_entity(author):
    if author.slug == EDITORIAL_BOARD_SLUG:
        return {"@type": "Organization", "name": author.name, "url": absolute(author.get_absolute_url())}
    data = {"@type": "Person", "name": author.name, "url": absolute(author.get_absolute_url())}
    if author.role:
        data["jobTitle"] = author.role
    return data


def article_json_ld(page, site_name):
    data = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "mainEntityOfPage": {"@type": "WebPage", "@id": page.full_url},
        "url": page.full_url,
        "headline": page.title[:110],
        "description": strip_tags(page.standfirst),
        "inLanguage": "en-IN",
        "isAccessibleForFree": True,
        "articleSection": page.section.title if page.section else None,
        "genre": page.get_article_type_display(),
        "keywords": ", ".join(page.tags.names()),
        "wordCount": page.word_count,
        "author": [author_entity(a) for a in page.authors],
        "publisher": publisher(site_name),
    }
    if page.display_date:
        data["datePublished"] = timezone.localtime(page.display_date).isoformat()
    modified = page.last_published_at or page.display_date
    if modified:
        data["dateModified"] = timezone.localtime(max(modified, page.display_date or modified)).isoformat()
    if page.hero_image:
        data["image"] = [absolute(page.hero_image.get_rendition(spec).url) for spec in IMAGE_SPECS]
    return {key: value for key, value in data.items() if value not in (None, "", [])}


def author_json_ld(author):
    entity = author_entity(author)
    if author.bio:
        entity["description"] = author.bio
    if author.twitter:
        entity["sameAs"] = [f"https://x.com/{author.twitter}"]
    return {"@context": "https://schema.org", "@type": "ProfilePage", "mainEntity": entity}


def website_json_ld(site_name, search_url):
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": site_name,
        "url": absolute("/"),
        "publisher": publisher(site_name),
        "potentialAction": {
            "@type": "SearchAction",
            "target": {"@type": "EntryPoint", "urlTemplate": absolute(search_url) + "?q={search_term_string}"},
            "query-input": "required name=search_term_string",
        },
    }
