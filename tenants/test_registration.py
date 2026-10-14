from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from tenants.models import Tenant, TenantRegistration, TenantMembership, TenantSettings, HotspotConfiguration


@override_settings(DEBUG=True, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', DEFAULT_FROM_EMAIL='conta@example.com')
class TenantRegistrationTests(TestCase):
    host = {'HTTP_HOST': 'novainfo.com.br'}

    def setUp(self):
        cache.clear()
        self.data = dict(username='marcos', email='marcos@example.com', password1='Secure-new-789!',
                         password2='Secure-new-789!', name='Marcos Wi-Fi')
        self.admin = get_user_model().objects.create_user('reviewer', is_staff=True)
        self.admin.user_permissions.add(Permission.objects.get(codename='manage_network', content_type__app_label='operations'))

    def test_registration_form_only_asks_for_account_and_business_name(self):
        response = self.client.get('/registro/', **self.host)
        self.assertContains(response, 'Usuário:')
        self.assertContains(response, 'Nome do estabelecimento:')
        self.assertNotContains(response, 'Nome do responsável')
        self.assertNotContains(response, 'Telefone / WhatsApp')
        self.assertNotContains(response, 'Cidade:')
        self.assertNotContains(response, 'Subdomínio desejado')

    def register(self):
        response = self.client.post('/registro/', self.data, **self.host)
        self.assertContains(response, 'Confira seu e-mail')
        registration = TenantRegistration.objects.get(slug='marcos')
        self.assertEqual(registration.responsible_name, '')
        self.assertEqual(registration.phone, '')
        self.assertEqual(registration.city, '')
        return registration

    def confirm(self):
        link = mail.outbox[0].body.splitlines()[1]
        self.client.post('/' + link.split('/', 3)[3], **self.host)

    def test_registration_confirmation_and_single_action_approval(self):
        self.assertContains(self.client.get('/', **self.host), 'href="/registro/"')
        registration = self.register()
        self.assertFalse(Tenant.objects.filter(slug='marcos').exists())
        self.assertFalse(TenantMembership.objects.filter(user=registration.user).exists())
        self.confirm()
        self.client.force_login(self.admin)
        self.assertContains(self.client.get('/accounts/painel/', **self.host), 'marcos.novainfo.com.br')
        path = f'/accounts/painel/cadastros/{registration.pk}/aprovar/'
        self.assertEqual(self.client.get(path, **self.host).status_code, 405)
        self.assertEqual(self.client.post(path, **self.host).status_code, 302)
        tenant = Tenant.objects.get(slug='marcos')
        self.assertEqual(TenantMembership.objects.get(tenant=tenant).role, 'owner')
        self.assertTrue(TenantSettings.objects.filter(tenant=tenant).exists())
        self.assertTrue(HotspotConfiguration.objects.filter(tenant=tenant).exists())
        self.client.post(path, **self.host)
        self.assertEqual(TenantMembership.objects.filter(tenant=tenant).count(), 1)
        self.client.logout()
        response = self.client.post('/accounts/login/', {'username': 'marcos@example.com', 'password': self.data['password1']}, HTTP_HOST='marcos.novainfo.com.br')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get('/painel/', HTTP_HOST='marcos.novainfo.com.br').status_code, 200)

    def test_unconfirmed_and_unauthorized_approval_are_blocked(self):
        registration = self.register()
        path = f'/accounts/painel/cadastros/{registration.pk}/aprovar/'
        self.client.force_login(registration.user)
        self.assertEqual(self.client.post(path, **self.host).status_code, 302)
        self.client.force_login(self.admin)
        self.client.post(path, **self.host)
        self.assertFalse(Tenant.objects.filter(slug='marcos').exists())

    def test_reserved_and_duplicate_requests_are_rejected(self):
        self.data['username'] = 'admin'
        self.assertContains(self.client.post('/registro/', self.data, **self.host), 'reservado')
        self.data['username'] = 'marcos'
        self.register()
        self.data.update(username='MARCOS', email='another@example.com')
        self.assertContains(self.client.post('/registro/', self.data, **self.host), 'já está em uso ou foi solicitado')

    def test_username_must_be_valid_as_a_subdomain(self):
        self.data['username'] = 'invalid_name'
        self.assertContains(
            self.client.post('/registro/', self.data, **self.host),
            'Use letras minúsculas, números e hífens em um subdomínio válido.',
        )

    def test_existing_subdomain_does_not_grant_access_or_leave_partial_records(self):
        registration = self.register()
        self.confirm()
        tenant = Tenant.objects.create(name='Existing', slug='marcos')
        self.client.force_login(self.admin)
        self.client.post(f'/accounts/painel/cadastros/{registration.pk}/aprovar/', **self.host)
        registration.refresh_from_db()
        self.assertIsNone(registration.tenant_id)
        self.assertFalse(TenantMembership.objects.filter(tenant=tenant).exists())
