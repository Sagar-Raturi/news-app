from django.urls import path

from . import views

app_name = "news"

urlpatterns = [
    path("search/", views.search, name="search"),
    path("authors/", views.author_list, name="author_list"),
    path("authors/<slug:slug>/", views.author_detail, name="author_detail"),
    path("tags/<slug:slug>/", views.tag_detail, name="tag_detail"),
    path("news-sitemap.xml", views.news_sitemap, name="news_sitemap"),
    path("feed/", views.LatestArticlesFeed(), name="feed"),
]
