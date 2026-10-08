from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from wagtail import urls as wagtail_urls
from wagtail.admin import urls as wagtailadmin_urls
from wagtail.contrib.sitemaps import Sitemap as PageSitemap
from wagtail.contrib.sitemaps.views import sitemap
from wagtail.documents import urls as wagtaildocs_urls

from news.sitemaps import AuthorSitemap, TagSitemap
from news.views import robots_txt
from newsdesk.live import workspace_events

SITEMAPS = {"pages": PageSitemap, "authors": AuthorSitemap, "tags": TagSitemap}

urlpatterns = [
    path("django-admin/", admin.site.urls),
    # Live agent activity (async, so outside the Wagtail admin URLs).
    path("newsdesk/live/<int:pk>/events/", workspace_events, name="newsdesk_live_events"),
    path("admin/", include(wagtailadmin_urls)),
    path("documents/", include(wagtaildocs_urls)),
    path("sitemap.xml", sitemap, {"sitemaps": SITEMAPS}, name="sitemap"),
    path("robots.txt", robots_txt, name="robots_txt"),
    path("", include("news.urls")),
]

if settings.DEBUG:
    from django.conf.urls.static import static
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns

    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Wagtail's page serving catch-all must come last.
urlpatterns += [path("", include(wagtail_urls))]
