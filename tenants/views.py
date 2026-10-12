from django.views.generic import TemplateView

from tenants.mixins import TenantAccessMixin


class DashboardView(TenantAccessMixin, TemplateView):
    template_name = "tenants/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["tenant"] = self.request.tenant
        return context
