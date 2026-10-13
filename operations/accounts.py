"""Administrative review of customer accounts and establishment access."""
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from tenants.account import AuthRateLimitMixin
from django.contrib.auth.views import LoginView
from tenants.models import Tenant, TenantMembership, AuditEvent
from operations.views import central_access


class ControlLoginView(AuthRateLimitMixin, LoginView):
    template_name = 'operations/login.html'
    next_page = '/accounts/painel/'

    def dispatch(self, request, *args, **kwargs):
        if not request.platform_host or request.tenant is not None:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.get_user()
        if not user.is_active or not user.is_staff or not user.has_perm('operations.manage_network'):
            form.add_error(None, 'Esta conta não possui acesso à área de controle.')
            return self.form_invalid(form)
        return super().form_valid(form)


class ApprovalForm(forms.Form):
    tenant = forms.ModelChoiceField(label='Estabelecimento', queryset=Tenant.objects.none())
    role = forms.ChoiceField(label='Permissão', choices=TenantMembership.Role.choices, initial='viewer')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tenant'].queryset = Tenant.objects.filter(is_active=True).order_by('name')


@central_access
def accounts_panel(request):
    users = get_user_model().objects.filter(is_staff=False, tenant_memberships__isnull=True).order_by('-date_joined')
    page = Paginator(users, 50).get_page(request.GET.get('page'))
    return render(request, 'operations/accounts.html', {'page_title': 'Controle de contas e aprovação', 'page_obj': page})


@central_access
@require_http_methods(['GET', 'POST'])
def approve_account(request, pk):
    user = get_object_or_404(get_user_model(), pk=pk, is_staff=False)
    form = ApprovalForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            user = get_user_model().objects.select_for_update().get(pk=user.pk)
            if not user.is_active:
                form.add_error(None, 'O usuário precisa confirmar o e-mail antes da aprovação.')
            else:
                tenant = form.cleaned_data['tenant']
                member, created = TenantMembership.objects.get_or_create(
                    tenant=tenant, user=user,
                    defaults={'role': form.cleaned_data['role'], 'is_active': True})
                if not created:
                    form.add_error(None, 'Esta associação já existe. Edite em Usuários e permissões.')
                else:
                    AuditEvent.objects.create(tenant=tenant, actor=request.user, action='aprovar acesso',
                                              object_type='tenantmembership', object_id=member.pk,
                                              fields_changed=['user', 'tenant', 'role', 'is_active'])
                    messages.success(request, f'Acesso de {user.get_username()} aprovado para {tenant.name}.')
                    return redirect('accounts-panel')
    return render(request, 'operations/approve_account.html', {'page_title': 'Aprovar acesso ao estabelecimento', 'account_user': user, 'form': form})
