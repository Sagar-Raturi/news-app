from django.utils.cache import patch_vary_headers


class HtmxVaryMiddleware:
    """Responses differ for HTMX requests (partials), so caches must key on it."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        patch_vary_headers(response, ["HX-Request"])
        return response
