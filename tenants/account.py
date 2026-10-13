from urllib.parse import urlsplit
from django.conf import settings
from django.contrib.auth import views as auth_views
from django import forms
from django.shortcuts import render, redirect
from django.views import View
from django.core.cache import cache
from django.http import HttpResponse
import hashlib


class AuthRateLimitMixin:
    """Bound authentication attempts per source address within each worker."""
    def dispatch(self, request, *args, **kwargs):
        if request.method == "POST":
            source = request.META.get("REMOTE_ADDR", "unknown")
            key = "auth-attempts:" + hashlib.sha256((request.path + source).encode()).hexdigest()
            if cache.add(key, 1, timeout=900):
                count = 1
            else:
                try:
                    count = cache.incr(key)
                except ValueError:
                    cache.set(key, 1, timeout=900)
                    count = 1
            if count > 10:
                response = HttpResponse("Muitas tentativas. Aguarde 15 minutos e tente novamente.", status=429)
                response["Retry-After"] = "900"
                return response
        return super().dispatch(request, *args, **kwargs)
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


class TenantLoginView(AuthRateLimitMixin, auth_views.LoginView):
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


from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm, PasswordResetForm
from django.core import signing
from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse
from django.http import HttpResponse


class SignupForm(UserCreationForm):
    email = forms.EmailField(label='E-mail')

    class Meta:
        model = get_user_model()
        fields = ('username', 'email')

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Não foi possível cadastrar este e-mail. Se já tem conta, recupere sua senha.')
        return email


class SignupView(AuthRateLimitMixin, View):
    def get(self, request):
        return render(request, 'registration/signup.html', {'form': SignupForm()})

    def post(self, request):
        form = SignupForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save(commit=False)
                    user.is_active = False
                    user.save()
                    token = signing.dumps({'user': user.pk, 'email': user.email}, salt='account-confirm')
                    link = request.build_absolute_uri(reverse('account-confirm', args=[token]))
                    send_mail('Confirme sua conta Nova Info',
                              f'Confirme seu e-mail pelo link abaixo (válido por 24 horas):\n{link}\n\n'
                              'O acesso ao estabelecimento depende de aprovação e associação pela administração.',
                              settings.DEFAULT_FROM_EMAIL, [user.email])
            except Exception:
                form.add_error(None, 'Não foi possível enviar a confirmação. Tente novamente mais tarde.')
            else:
                return render(request, 'registration/message.html', {
                    'title': 'Confira seu e-mail',
                    'message': 'Enviamos um link para confirmar sua conta. Depois, solicite à administração a associação ao seu estabelecimento.'})
        return render(request, 'registration/signup.html', {'form': form})


class ConfirmAccountView(View):
    def get(self, request, token):
        # Email scanners must not activate accounts merely by following a link.
        return render(request, 'registration/confirm.html', {})

    def post(self, request, token):
        try:
            data = signing.loads(token, salt='account-confirm', max_age=86400)
            updated = get_user_model().objects.filter(pk=data['user'], email=data['email'], is_active=False).update(is_active=True)
            if not updated:
                raise signing.BadSignature
        except (signing.BadSignature, KeyError):
            return render(request, 'registration/message.html', {'title': 'Link inválido', 'message': 'Este link expirou ou já foi utilizado.'}, status=400)
        return render(request, 'registration/message.html', {'title': 'E-mail confirmado', 'message': 'Sua conta foi confirmada. A administração precisa associá-la ao estabelecimento antes do acesso ao painel.'})


class TenantPasswordResetForm(PasswordResetForm):
    def __init__(self, *args, tenant=None, **kwargs):
        self.tenant = tenant
        super().__init__(*args, **kwargs)

    def get_users(self, email):
        from tenants.db_context import tenant_database_context
        for user in super().get_users(email):
            if self.tenant is None:
                yield user
            else:
                with tenant_database_context(self.tenant.pk, user.pk):
                    allowed = TenantMembership.objects.filter(tenant=self.tenant, user=user, is_active=True).exists()
                if allowed:
                    yield user


class TenantPasswordResetView(AuthRateLimitMixin, auth_views.PasswordResetView):
    form_class = TenantPasswordResetForm
    template_name = 'registration/password_reset_form.html'
    email_template_name = 'registration/password_reset_email.txt'
    subject_template_name = 'registration/password_reset_subject.txt'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['tenant'] = self.request.tenant
        return kwargs

    def form_valid(self, form):
        try:
            return super().form_valid(form)
        except Exception:
            return HttpResponse('Não foi possível processar a solicitação. Tente novamente mais tarde.', status=503)
