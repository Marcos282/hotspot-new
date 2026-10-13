from urllib.parse import urlsplit

from django.conf import settings
from django.http import Http404

from tenants.models import Tenant


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.root_domain = settings.TENANT_ROOT_DOMAIN.lower().rstrip(".")

    def __call__(self, request):
        from tenants.checks import verify_runtime_database
        verify_runtime_database()
        from tenants.db_context import tenant_database_context
        from tenants.models import TenantMembership
        host_is_root = self.is_platform_host(request)
        request.platform_host = host_is_root
        central = bool(host_is_root and request.user.is_authenticated and request.user.is_active
                       and request.user.is_staff and request.user.has_perm('operations.manage_network')
                       and (request.path.startswith('/central/') or request.path.startswith('/admin/') or request.path.startswith('/accounts/painel/')))
        user_id = request.user.pk if request.user.is_authenticated else None
        with tenant_database_context(None, user_id, central=central):
            request.tenant = self.resolve_tenant(request)
            request.tenant_membership = None
            if request.tenant and request.user.is_authenticated:
                request.tenant_membership = TenantMembership.objects.filter(
                    tenant=request.tenant, user=request.user, is_active=True
                ).first()
            with tenant_database_context(
                request.tenant.pk if request.tenant_membership else None,
                user_id, central=central,
            ):
                from django.db import connection
                if connection.vendor == 'postgresql' and request.tenant_membership:
                    request.tenant = Tenant.objects.get(pk=request.tenant.pk)
                # Protect every panel route, including future views that omit a mixin.
                if request.path == '/painel' or request.path.startswith('/painel/'):
                    if not request.user.is_authenticated:
                        from django.contrib.auth.views import redirect_to_login
                        return redirect_to_login(request.get_full_path())
                    if not request.tenant_membership or not request.tenant.is_active:
                        raise Http404
                response = self.get_response(request)
                if hasattr(response, 'render') and not response.is_rendered:
                    response.render()
                return response

    def is_platform_host(self, request):
        host = urlsplit(f"//{request.get_host()}").hostname.lower().rstrip('.')
        return host == self.root_domain or not host.endswith('.'+self.root_domain) or host in {'www.'+self.root_domain,'gestao.'+self.root_domain,'admin.'+self.root_domain}

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

        from django.db import connection
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute('SELECT id,name,slug,is_active FROM public.novainfo_resolve_tenant(%s)',[subdomain])
                row=cursor.fetchone()
            if row is None:
                raise Http404
            return Tenant(pk=row[0],name=row[1],slug=row[2],is_active=row[3])
        try:
            tenant = Tenant.objects.get(slug=subdomain, is_active=True)
        except Tenant.DoesNotExist:
            raise Http404 from None
        return tenant
