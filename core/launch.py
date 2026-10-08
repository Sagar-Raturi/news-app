"""What still stands between the site and a public launch.

Shown on the Wagtail dashboard (editors and admins) and by
`python manage.py launch_check` (exits 1 while anything is missing).
"""

import os
from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import get_user_model
from wagtail.models import Page, Site

from core.models import SiteSettings
from core.trust_pages import TRUST_PAGE_SLUGS

# Checks the code can't make; the owner confirms them before launch.
MANUAL_CHECKS = [
    "A lawyer has reviewed the Terms of use and Privacy policy.",
    "Cloudflare Access protects /admin/ (the privacy policy promises a second sign-in step for staff).",
    "The publisher's details have been furnished to the Ministry of Information and Broadcasting (IT Rules 2021, rule 18).",
    "An uptime monitor watches /healthz/ and the homepage.",
]


@dataclass
class Check:
    label: str
    ok: bool
    fix: str = ""


def _demo_logins():
    from core.management.commands.seed_demo import DEMO_USERS

    users = get_user_model().objects.filter(username__in=[row[0] for row in DEMO_USERS], is_active=True)
    # Demo logins use the username as the password.
    return [user.username for user in users if user.check_password(user.username)]


def launch_checks(site=None):
    from news.models import ArticlePage

    site = site or Site.objects.filter(is_default_site=True).select_related("root_page").first()
    publisher = SiteSettings.for_site(site)
    checks = [
        Check(
            "Publisher details: legal name, registered address and contact email",
            bool(publisher.legal_name and publisher.registered_address and publisher.contact_email),
            "Settings → Site settings → Publisher details.",
        ),
        Check(
            "Grievance Officer: name and email",
            bool(publisher.grievance_officer_name and publisher.grievance_email),
            "Settings → Site settings → Grievance redressal. The officer must live in India.",
        ),
        Check(
            "Self-regulating body named",
            bool(publisher.self_regulatory_body),
            "Join a self-regulating body for news publishers (IT Rules 2021, rule 12) and name it in Site settings.",
        ),
    ]

    pages = {page.slug: page for page in Page.objects.child_of(site.root_page).filter(slug__in=TRUST_PAGE_SLUGS.values())}
    for slug in TRUST_PAGE_SLUGS.values():
        page = pages.get(slug)
        legal = slug in {"terms", "privacy"}
        checks.append(
            Check(
                f"‘{page.title if page else slug}’ page published",
                bool(page and page.live),
                ("Have it reviewed by a lawyer, then publish it." if legal else "Review the draft and publish it.")
                if page
                else "Missing: run `python manage.py bootstrap_site` to create the draft.",
            )
        )

    checks += [
        Check(
            "Demonstration notice switched off",
            not publisher.demo_notice,
            "Settings → Site settings: untick ‘Demo notice’.",
        ),
        Check(
            "No demo logins",
            not _demo_logins(),
            "Delete the demo users (admin, editor, writer) in Settings → Users.",
        ),
        Check(
            "At least one article published",
            ArticlePage.objects.live().exists(),
            "Approve and publish your launch articles.",
        ),
        Check(
            "AI agents can write",
            settings.NEWSDESK_WRITER == "fake" or bool(os.environ.get("ANTHROPIC_API_KEY")),
            "Set ANTHROPIC_API_KEY in .env.production (or write the launch articles by hand).",
        ),
    ]
    if settings.DEPLOYED:
        checks.append(
            Check(
                "Email is really sent",
                "console" not in settings.EMAIL_BACKEND,
                "Set DJANGO_EMAIL_BACKEND and the EMAIL_* variables (complaint acknowledgements depend on it).",
            )
        )
    return checks
