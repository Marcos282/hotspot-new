from urllib.parse import urlsplit

from django.conf import settings
from django.http import Http404

from tenants.models import Tenant


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.root_domain = settings.TENANT_ROOT_DOMAIN.lower().rstrip(".")

    def __call__(self, request):
        request.tenant = self.resolve_tenant(request)
        return self.get_response(request)

    def resolve_tenant(self, request):
        host = urlsplit(f"//{request.get_host()}").hostname
        if not host:
            raise Http404
        host = host.lower().rstrip(".")

        if host == self.root_domain:
            return None
        suffix = f".{self.root_domain}"
        if not host.endswith(suffix):
            return None

        subdomain = host[: -len(suffix)]
        if not subdomain or "." in subdomain:
            raise Http404
        if subdomain in {"www", "gestao", "admin", "api", "static"}:
            return None

        try:
            tenant = Tenant.objects.get(slug=subdomain, is_active=True)
        except Tenant.DoesNotExist:
            raise Http404 from None
        return tenant
