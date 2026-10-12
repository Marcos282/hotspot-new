from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404

from tenants.models import TenantMembership


class TenantAccessMixin(LoginRequiredMixin):
    """Restrict a tenant view to active members without disclosing tenant existence."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        tenant = getattr(request, "tenant", None)
        if tenant is None or not tenant.is_active:
            raise Http404

        has_membership = TenantMembership.objects.filter(
            tenant=tenant, user=request.user, is_active=True
        ).exists()
        if not has_membership:
            raise Http404

        return super().dispatch(request, *args, **kwargs)
