from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from tenants.models import Tenant, TenantMembership, AuditEvent


@override_settings(DEBUG=True)
class AccountsPanelTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user('reviewer', password='Admin-strong-123!', is_staff=True)
        self.admin.user_permissions.add(Permission.objects.get(codename='manage_network', content_type__app_label='operations'))
        self.customer = get_user_model().objects.create_user('customer', email='customer@example.com', password='Customer-strong-123!')
        self.tenant = Tenant.objects.create(name='Hotel', slug='hotel')
        self.host = {'HTTP_HOST': 'novainfo.com.br'}

    def test_anonymous_redirects_to_control_login(self):
        response = self.client.get('/accounts/painel/', **self.host)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/painel/login/', response.url)

    def test_customer_and_unprivileged_staff_are_denied(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get('/accounts/painel/', **self.host).status_code, 403)
        self.customer.is_staff = True
        self.customer.save()
        self.assertEqual(self.client.get('/accounts/painel/', **self.host).status_code, 403)

    def test_approval_requires_post_and_records_audit(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get('/accounts/painel/', **self.host), self.customer.email)
        path = f'/accounts/painel/usuarios/{self.customer.pk}/aprovar/'
        self.assertEqual(self.client.get(path, **self.host).status_code, 200)
        self.assertFalse(TenantMembership.objects.filter(user=self.customer).exists())
        response = self.client.post(path, {'tenant': self.tenant.pk, 'role': 'viewer'}, **self.host)
        self.assertEqual(response.status_code, 302)
        member = TenantMembership.objects.get(user=self.customer, tenant=self.tenant)
        self.assertEqual(member.role, 'viewer')
        self.assertTrue(member.is_active)
        self.assertTrue(AuditEvent.objects.filter(actor=self.admin, action='aprovar acesso').exists())
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get('/painel/', HTTP_HOST='hotel.novainfo.com.br').status_code, 200)

    def test_inactive_account_cannot_be_approved(self):
        self.customer.is_active = False
        self.customer.save()
        self.client.force_login(self.admin)
        response = self.client.post(f'/accounts/painel/usuarios/{self.customer.pk}/aprovar/', {'tenant': self.tenant.pk, 'role': 'owner'}, **self.host)
        self.assertContains(response, 'confirmar o e-mail')
        self.assertFalse(TenantMembership.objects.filter(user=self.customer).exists())

    def test_admin_cannot_use_control_on_tenant_host(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get('/accounts/painel/', HTTP_HOST='hotel.novainfo.com.br').status_code, 403)

    def test_customer_credentials_rejected_by_control_login(self):
        response = self.client.post('/accounts/painel/login/', {'username': 'customer@example.com', 'password': 'Customer-strong-123!'}, **self.host)
        self.assertContains(response, 'não possui acesso')
        self.assertNotIn('_auth_user_id', self.client.session)
