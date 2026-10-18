from datetime import timedelta
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.db.models import Sum
from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView
from tenants.mixins import TenantAccessMixin
from tenants.models import Device, AccessPlan, Sale, Payment, AccessSession, HotspotConfiguration, BrandImage, AuditEvent, TenantMembership
from tenants.forms import DeviceForm, AccessPlanForm, HotspotForm, BrandImageForm


SECTIONS = {
    'equipamentos': (Device, DeviceForm, 'Equipamentos MikroTik'),
    'planos': (AccessPlan, AccessPlanForm, 'Planos de acesso'),
    'vendas': (Sale, None, 'Vendas'),
    'pagamentos': (Payment, None, 'Recebimentos do estabelecimento'),
    'online': (AccessSession, None, 'Usuários online'),
    'registros': (AccessSession, None, 'Registros de acesso'),
    'auditoria': (AuditEvent, None, 'Atividades administrativas'),
}


def membership(request):
    return request.tenant_membership


def require_editor(request):
    if membership(request).role not in [TenantMembership.Role.OWNER, TenantMembership.Role.ADMIN]:
        raise PermissionDenied


def audit(request, action, obj, fields_changed=()):
    AuditEvent.objects.create(tenant=request.tenant, actor=request.user, action=action, object_type=obj._meta.model_name, object_id=obj.pk,fields_changed=list(fields_changed))


class DashboardView(TenantAccessMixin, TemplateView):
    template_name = 'tenants/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tenant = self.request.tenant
        context.update(tenant=tenant, page_title='Visão geral', membership=membership(self.request))
        context['device_count'] = Device.objects.for_tenant(tenant).count()
        context['tenant_devices'] = list(Device.objects.for_tenant(tenant).order_by('name').values('id','name','management_ip','enabled')[:20])
        context['plan_count'] = AccessPlan.objects.for_tenant(tenant).count()
        context['online_count'] = AccessSession.objects.for_tenant(tenant).filter(ended_at__isnull=True, last_seen__gte=timezone.now()-timedelta(minutes=5)).count()
        context['paid_total'] = Payment.objects.for_tenant(tenant).filter(method='cash',status='paid').aggregate(value=Sum('amount'))['value'] or 0
        context['sale_count'] = Sale.objects.for_tenant(tenant).count()
        context['database_isolation'] = connection.vendor == 'postgresql'
        return context


class RecordsView(TenantAccessMixin, TemplateView):
    template_name = 'tenants/records.html'

    def get_context_data(self, **kwargs):
        section = self.kwargs['section']
        if section not in SECTIONS:
            raise Http404
        if section in ['registros', 'auditoria']:
            require_editor(self.request)
        model, form, title = SECTIONS[section]
        query = model.objects.for_tenant(self.request.tenant).order_by('-pk')
        if section == 'online':
            query = query.filter(ended_at__isnull=True, last_seen__gte=timezone.now()-timedelta(minutes=5))
        from django.core.paginator import Paginator
        page = Paginator(query, 50).get_page(self.request.GET.get('page'))
        columns = {
            'equipamentos': [('name','Nome'),('management_ip','Endereço IP'),('routeros_version','RouterOS'),('enabled','Habilitado'),('last_seen','Última comunicação')],
            'planos': [('name','Plano'),('duration_minutes','Minutos'),('price','Valor (R$)'),('speed_limit','Velocidade'),('enabled','Ativo')],
            'vendas': [('reference','Referência'),('duration_minutes','Minutos vendidos'),('amount','Valor (R$)'),('status','Situação'),('created_at','Data')],
            'pagamentos': [('provider_reference','Referência'),('get_method_display','Forma'),('amount','Valor (R$)'),('status','Situação'),('received_by','Registrado por'),('received_at','Recebido em')],
            'online': [('username','Usuário'),('started_at','Início'),('last_seen','Última atualização')],
            'registros': [('username','Usuário'),('started_at','Início'),('ended_at','Fim'),('bytes_used','Bytes')],
            'auditoria': [('actor','Usuário'),('action','Ação'),('object_type','Cadastro'),('object_id','ID'),('created_at','Data')],
        }[section]
        rows = [{'pk': obj.pk, 'values': [getattr(obj, field)() if callable(getattr(obj, field)) else getattr(obj, field) for field, label in columns]} for obj in page]
        context = super().get_context_data(**kwargs)
        context.update(tenant=self.request.tenant, membership=membership(self.request), page_title=title, section=section, columns=[label for field,label in columns], rows=rows, page_obj=page, editable=bool(form) and membership(self.request).role in ['owner','admin'], can_register_cash=section=='vendas' and membership(self.request).role in ['owner','admin','staff'])
        return context


class RecordEditView(TenantAccessMixin, View):
    def handle(self, request, section, pk=None):
        require_editor(request)
        if section not in SECTIONS or SECTIONS[section][1] is None:
            raise Http404
        model, form_class, title = SECTIONS[section]
        obj = get_object_or_404(model.objects.for_tenant(request.tenant), pk=pk) if pk else model(tenant=request.tenant)
        form = form_class(request.POST if request.method == 'POST' else None, instance=obj)
        if request.method == 'POST' and form.is_valid():
            with transaction.atomic():
                obj = form.save()
                audit(request, 'editar' if pk else 'criar', obj, form.changed_data)
            messages.success(request, 'Cadastro salvo.')
            return redirect('tenants:records', section=section)
        from django.shortcuts import render
        return render(request, 'tenants/form.html', dict(tenant=request.tenant, membership=membership(request), page_title=title, form=form))

    get = handle
    post = handle


class HotspotView(TenantAccessMixin, View):
    def handle(self, request):
        require_editor(request)
        obj = HotspotConfiguration.objects.for_tenant(request.tenant).first() or HotspotConfiguration(tenant=request.tenant)
        form = HotspotForm(request.POST if request.method == 'POST' else None, instance=obj)
        if request.method == 'POST' and form.is_valid():
            with transaction.atomic():
                audit(request, 'configurar portal', form.save(), form.changed_data)
            messages.success(request, 'Configuração salva. A publicação no roteador depende da integração.')
            return redirect('tenants:hotspot')
        from django.shortcuts import render
        return render(request, 'tenants/form.html', dict(tenant=request.tenant, membership=membership(request), page_title='Página de Hotspot', form=form))

    get = handle
    post = handle


class ImagesView(TenantAccessMixin, View):
    def handle(self, request):
        require_editor(request)
        form = BrandImageForm(request.POST if request.method == 'POST' else None, request.FILES if request.method == 'POST' else None)
        if request.method == 'POST' and form.is_valid():
            with transaction.atomic():
                obj = BrandImage.objects.create(tenant=request.tenant, kind=form.cleaned_data['kind'], title=form.cleaned_data['title'], data=form.cleaned_data['image'])
                audit(request, 'enviar imagem', obj, ['kind','title','data'])
            messages.success(request, 'Imagem salva no ambiente do estabelecimento.')
            return redirect('tenants:images')
        from django.shortcuts import render
        return render(request, 'tenants/form.html', dict(tenant=request.tenant, membership=membership(request), page_title='Logotipo e publicidade', form=form, images=BrandImage.objects.for_tenant(request.tenant).order_by('-pk')[:50]))

    get = handle
    post = handle


class ImageView(TenantAccessMixin, View):
    def get(self, request, pk):
        require_editor(request)
        image = get_object_or_404(BrandImage.objects.for_tenant(request.tenant), pk=pk)
        response = HttpResponse(bytes(image.data), content_type='image/png')
        response['X-Content-Type-Options'] = 'nosniff'
        response['Cache-Control'] = 'private, no-store'
        return response


class TenantReportView(TenantAccessMixin, View):
    def get(self,request):
        require_editor(request)
        from operations.views import report_context
        from django.shortcuts import render
        return render(request,'tenants/reports.html',dict(tenant=request.tenant,membership=membership(request),page_title='Relatórios de acesso e disponibilidade',**report_context(request,tenant=request.tenant)))


class HotspotPreviewView(TenantAccessMixin, View):
    def get(self,request):
        require_editor(request)
        from django.shortcuts import render
        import base64
        config=HotspotConfiguration.objects.for_tenant(request.tenant).first()
        images=[{'kind':image.kind,'title':image.title,'src':'data:image/png;base64,'+base64.b64encode(bytes(image.data)).decode()} for image in BrandImage.objects.for_tenant(request.tenant).order_by('-pk')[:6]]
        return render(request,'tenants/hotspot_preview.html',dict(tenant=request.tenant,config=config,images=images))
