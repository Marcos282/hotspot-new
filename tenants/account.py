from urllib.parse import urlsplit
from django.conf import settings
from django.contrib.auth import views as auth_views
from django import forms
from django.shortcuts import render, redirect
from django.views import View
from django.core.cache import cache
from django.http import HttpResponse
import hashlib
import logging

logger = logging.getLogger(__name__)


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


class EmailAuthenticationForm(auth_views.AuthenticationForm):
    username = forms.EmailField(label='E-mail', widget=forms.EmailInput(attrs={'autocomplete': 'email', 'autofocus': True}))
    error_messages = {
        'invalid_login': 'E-mail ou senha inválidos.',
        'inactive': 'Esta conta está inativa.',
    }


def authorized_workspaces(user):
    from tenants.db_context import tenant_database_context
    from tenants.models import Tenant
    workspaces = []
    with tenant_database_context(None, user.pk):
        tenant_ids = list(TenantMembership.objects.filter(user=user, is_active=True).values_list('tenant_id', flat=True))
    for tenant_id in tenant_ids:
        with tenant_database_context(tenant_id, user.pk):
            tenant = Tenant.objects.filter(pk=tenant_id, is_active=True).first()
            if tenant:
                workspaces.append(tenant)
    return workspaces


def workspace_login_url(request, user, tenant):
    # A separate, short-lived database session acts as a single-use login ticket.
    from django.contrib.sessions.backends.db import SessionStore
    ticket = SessionStore()
    ticket['workspace_login'] = {'user': user.pk, 'tenant': tenant.pk, 'auth_hash': user.get_session_auth_hash()}
    ticket.set_expiry(60)
    ticket.create()
    host = urlsplit('//' + request.get_host())
    local = settings.DEBUG and host.hostname in {'localhost', '127.0.0.1'}
    domain = 'localhost' if local else settings.TENANT_ROOT_DOMAIN
    port = f':{host.port}' if settings.DEBUG and host.port else ''
    scheme = request.scheme if settings.DEBUG else 'https'
    return f'{scheme}://{tenant.slug}.{domain}{port}/accounts/entrar/{ticket.session_key}/'


class AccountView(AuthRateLimitMixin, auth_views.LoginView):
    template_name = 'registration/workspace.html'
    authentication_form = EmailAuthenticationForm

    def form_valid(self, form):
        user = form.get_user()
        workspaces = authorized_workspaces(user)
        if self.request.tenant:
            workspaces = [tenant for tenant in workspaces if tenant.pk == self.request.tenant.pk]
            if workspaces:
                return super().form_valid(form)
        if not workspaces:
            if self.request.platform_host and user.is_staff and user.has_perm('operations.manage_network'):
                from django.contrib.auth import login
                login(self.request, user)
                return redirect('accounts-panel')
            form.add_error(None, 'Seu acesso ainda não foi aprovado ou o estabelecimento está inativo.')
            return self.form_invalid(form)
        links = [{'name': tenant.name, 'url': workspace_login_url(self.request, user, tenant)} for tenant in workspaces]
        if len(links) == 1:
            response = redirect(links[0]['url'])
        else:
            response = render(self.request, 'registration/choose_workspace.html', {'workspaces': links})
        response['Cache-Control'] = 'no-store'
        response['Referrer-Policy'] = 'no-referrer'
        return response


class WorkspaceLoginView(View):
    def get(self, request, ticket):
        from django.contrib.sessions.models import Session
        from django.utils import timezone
        from django.utils.crypto import constant_time_compare
        from django.contrib.auth import login, get_user_model
        from django.db import transaction
        if not request.tenant:
            return redirect('account')
        with transaction.atomic():
            stored = Session.objects.select_for_update().filter(session_key=ticket, expire_date__gt=timezone.now()).first()
            data = stored.get_decoded().get('workspace_login') if stored else None
            if not data or data.get('tenant') != request.tenant.pk:
                return redirect('login')
            stored.delete()
            user = get_user_model().objects.filter(pk=data.get('user'), is_active=True).first()
            if not user or not constant_time_compare(data.get('auth_hash', ''), user.get_session_auth_hash()):
                return redirect('login')
            if not any(tenant.pk == request.tenant.pk for tenant in authorized_workspaces(user)):
                return redirect('login')
            login(request, user, backend='tenants.auth_backend.EmailBackend')
        response = redirect('tenants:dashboard')
        response['Cache-Control'] = 'no-store'
        response['Referrer-Policy'] = 'no-referrer'
        return response


class TenantLoginView(AuthRateLimitMixin, auth_views.LoginView):
    authentication_form = EmailAuthenticationForm
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
from django.core.exceptions import ValidationError
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


class TenantRegistrationForm(SignupForm):
    name = forms.CharField(label='Nome do estabelecimento', max_length=150)

    def clean_username(self):
        from tenants.models import Tenant, TenantRegistration

        username = self.cleaned_data['username']
        slug = username.lower()
        try:
            tenant_slug_validator(slug)
            validate_tenant_slug(slug)
        except ValidationError as error:
            raise forms.ValidationError(error.messages) from error
        if Tenant.objects.filter(slug=slug).exists() or TenantRegistration.objects.filter(slug=slug).exists():
            raise forms.ValidationError('Este endereço já está em uso ou foi solicitado.')
        return username


class SignupView(AuthRateLimitMixin, View):
    form_class = SignupForm
    template_name = 'registration/signup.html'
    def get(self, request):
        return render(request, self.template_name, {'form': self.form_class()})

    def post(self, request):
        form = self.form_class(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save(commit=False)
                    user.is_active = False
                    user.save()
                    if isinstance(form, TenantRegistrationForm):
                        from tenants.models import TenantRegistration
                        TenantRegistration.objects.create(
                            user=user,
                            name=form.cleaned_data['name'],
                            responsible_name='',
                            phone='',
                            city='',
                            slug=form.cleaned_data['username'].lower(),
                        )
                    token = signing.dumps({'user': user.pk, 'email': user.email}, salt='account-confirm')
                    link = request.build_absolute_uri(reverse('account-confirm', args=[token]))
                    send_mail('Confirme sua conta Nova Info',
                              f'Confirme seu e-mail pelo link abaixo (válido por 24 horas):\n{link}\n\n'
                              'O acesso ao estabelecimento depende de aprovação e associação pela administração.',
                              settings.DEFAULT_FROM_EMAIL, [user.email])
            except Exception as error:
                logger.error('Falha ao cadastrar conta/enviar confirmação: tipo=%s', type(error).__name__)
                form.add_error(None, 'Não foi possível enviar a confirmação. Tente novamente mais tarde.')
            else:
                return render(request, 'registration/message.html', {
                    'title': 'Confira seu e-mail',
                    'message': 'Enviamos um link para confirmar sua conta. Após a confirmação, a administração poderá aprovar seu cadastro e liberar o painel.'})
        return render(request, self.template_name, {'form': form})


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
        except Exception as error:
            logger.error('Falha ao enviar recuperação de senha: tipo=%s', type(error).__name__)
            return HttpResponse('Não foi possível processar a solicitação. Tente novamente mais tarde.', status=503)


class TenantRegistrationView(SignupView):
    form_class = TenantRegistrationForm
    template_name = 'registration/tenant_signup.html'

    def dispatch(self, request, *args, **kwargs):
        if request.tenant:
            return redirect(f'https://{settings.TENANT_ROOT_DOMAIN}/registro/')
        return super().dispatch(request, *args, **kwargs)


from django.contrib.admin.forms import AdminAuthenticationForm


class EmailAdminAuthenticationForm(AdminAuthenticationForm):
    username = forms.EmailField(label='E-mail', widget=forms.EmailInput(attrs={'autocomplete': 'email', 'autofocus': True}))
