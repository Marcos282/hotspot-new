from urllib.parse import urlsplit
from django.contrib.auth import get_user_model, authenticate
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.test import TestCase, override_settings
from django.core.cache import cache
from tenants.models import Tenant, TenantMembership


@override_settings(DEBUG=True)
class EmailLoginTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user('marcos', email='marcos@example.com', password='Secure-email-789!')
        self.tenant = Tenant.objects.create(name='Marcos', slug='marcos')
        TenantMembership.objects.create(tenant=self.tenant, user=self.user, role='owner')
        self.credentials = {'username': 'MARCOS@example.com', 'password': 'Secure-email-789!'}

    def test_authentication_uses_email_and_rejects_username_and_duplicates(self):
        self.assertEqual(authenticate(username='MARCOS@example.com', password=self.credentials['password']), self.user)
        self.assertIsNone(authenticate(username='marcos', password=self.credentials['password']))
        get_user_model().objects.create_user('duplicate', email='marcos@example.com', password=self.credentials['password'])
        self.assertIsNone(authenticate(username='marcos@example.com', password=self.credentials['password']))

    def test_root_login_transfers_to_tenant_once(self):
        self.assertContains(self.client.get('/minha-conta/'), 'type="email"')
        response = self.client.post('/minha-conta/', self.credentials, HTTP_HOST='127.0.0.1:8001')
        self.assertEqual(response.status_code, 302)
        url = urlsplit(response.url)
        self.assertEqual(url.netloc, 'marcos.localhost:8001')
        response = self.client.get(url.path, HTTP_HOST=url.netloc)
        self.assertEqual(response.url, '/painel/')
        self.assertEqual(self.client.get('/painel/', HTTP_HOST=url.netloc).status_code, 200)
        self.client.logout()
        self.assertEqual(self.client.get(url.path, HTTP_HOST=url.netloc).url, '/accounts/login/')

    def test_ticket_is_bound_to_tenant_and_password(self):
        other = Tenant.objects.create(name='Other', slug='other')
        response = self.client.post('/minha-conta/', self.credentials, HTTP_HOST='novainfo.com.br')
        path = urlsplit(response.url).path
        self.assertEqual(self.client.get(path, HTTP_HOST='other.novainfo.com.br').url, '/accounts/login/')
        self.user.set_password('Changed-password-123!')
        self.user.save()
        self.assertEqual(self.client.get(path, HTTP_HOST='marcos.novainfo.com.br').url, '/accounts/login/')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_expired_ticket_and_unapproved_account_cannot_enter(self):
        from django.utils import timezone
        from datetime import timedelta
        response = self.client.post('/minha-conta/', self.credentials, HTTP_HOST='novainfo.com.br')
        path = urlsplit(response.url).path
        Session.objects.filter(session_key=path.split('/')[-2]).update(expire_date=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.client.get(path, HTTP_HOST='marcos.novainfo.com.br').url, '/accounts/login/')
        TenantMembership.objects.filter(user=self.user).update(is_active=False)
        self.assertContains(self.client.post('/minha-conta/', self.credentials), 'ainda não foi aprovado')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_multiple_workspaces_offer_only_authorized_choices(self):
        tenant = Tenant.objects.create(name='Second', slug='second')
        TenantMembership.objects.create(tenant=tenant, user=self.user)
        response = self.client.post('/minha-conta/', self.credentials)
        self.assertContains(response, 'Escolha seu estabelecimento')
        self.assertContains(response, 'Second')

    def test_tenant_and_admin_login_use_email(self):
        self.assertEqual(self.client.post('/accounts/login/', self.credentials, HTTP_HOST='marcos.novainfo.com.br').status_code, 302)
        self.client.logout()
        self.user.is_staff = True
        self.user.save()
        self.user.user_permissions.add(Permission.objects.get(codename='manage_network', content_type__app_label='operations'))
        self.assertEqual(self.client.post('/accounts/painel/login/', self.credentials, HTTP_HOST='novainfo.com.br').status_code, 302)
        self.client.logout()
        self.assertContains(self.client.get('/admin/login/', HTTP_HOST='novainfo.com.br'), 'type="email"')
