from urllib.parse import urlsplit
from django.conf import settings
from django.contrib.auth import views as auth_views
from django import forms
from django.shortcuts import render, redirect
from django.views import View
from tenants.models import TenantMembership, tenant_slug_validator, validate_tenant_slug


class WorkspaceForm(forms.Form):
    slug = forms.CharField(label='Subdomínio do estabelecimento', max_length=63, validators=[tenant_slug_validator, validate_tenant_slug])

    def clean_slug(self):
        return self.cleaned_data['slug'].lower()


class AccountView(View):
    def get(self, request):
        if request.tenant:
            return redirect('tenants:dashboard' if request.user.is_authenticated else 'login')
        return render(request, 'registration/workspace.html', {'form': WorkspaceForm()})

    def post(self, request):
        form = WorkspaceForm(request.POST)
        if form.is_valid():
            host = urlsplit('//' + request.get_host())
            port = f':{host.port}' if settings.DEBUG and host.port else ''
            scheme = request.scheme if settings.DEBUG else 'https'
            return redirect(f"{scheme}://{form.cleaned_data['slug']}.{settings.TENANT_ROOT_DOMAIN}{port}/accounts/login/")
        return render(request, 'registration/workspace.html', {'form': form})


class TenantLoginView(auth_views.LoginView):
    template_name = 'registration/login.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.tenant:
            return redirect('account')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        from tenants.db_context import tenant_database_context
        with tenant_database_context(self.request.tenant.pk, form.get_user().pk):
            authorized = TenantMembership.objects.filter(tenant=self.request.tenant, user=form.get_user(), is_active=True).exists()
        if not authorized:
            form.add_error(None, 'Esta conta não possui acesso a este estabelecimento.')
            return self.form_invalid(form)
        return super().form_valid(form)
