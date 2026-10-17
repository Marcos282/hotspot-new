from django.views.generic import TemplateView
from operations.server_status import wireguard_server_status
from operations.views import state
from tenants.mixins import TenantAccessMixin
from tenants.models import Device


class StatusView(TenantAccessMixin, TemplateView):
    template_name = 'tenants/status.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tenant = self.request.tenant
        context.update(
            tenant=tenant, membership=self.request.tenant_membership,
            page_title='Status', wireguard_server=wireguard_server_status(None, require_configuration=False),
            states=[state(device) for device in Device.objects.for_tenant(tenant).select_related('tenant', 'health').order_by('name')],
        )
        return context

    def render_to_response(self, context, **response_kwargs):
        response = super().render_to_response(context, **response_kwargs)
        response['Cache-Control'] = 'no-store'
        return response
