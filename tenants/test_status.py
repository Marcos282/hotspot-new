from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from tenants.models import Tenant, TenantMembership, Device


@override_settings(DEBUG=True)
class PanelStatusTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Nessa', slug='nessa')
        self.user = get_user_model().objects.create_user('nessa')
        TenantMembership.objects.create(user=self.user, tenant=self.tenant, role='owner')
        Device.objects.create(tenant=self.tenant, name='Meu roteador', management_ip='10.10.0.2')
        other = Tenant.objects.create(name='Outro', slug='outro')
        Device.objects.create(tenant=other, name='Roteador privado', management_ip='10.10.0.3')
        self.host = {'HTTP_HOST': 'nessa.novainfo.com.br'}

    def test_anonymous_needs_login(self):
        self.assertEqual(self.client.get('/painel/status/', **self.host).status_code, 302)

    def test_status_and_menu_only_show_own_devices(self):
        self.client.force_login(self.user)
        with patch('tenants.status.wireguard_server_status', return_value={'label': 'Ativo'}) as status:
            response = self.client.get('/painel/status/', **self.host)
        self.assertContains(response, '/painel/status/')
        self.assertContains(response, 'Meu roteador')
        self.assertNotContains(response, 'Roteador privado')
        status.assert_called_once_with(None, require_configuration=False)

    def test_other_tenant_is_denied(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/painel/status/', HTTP_HOST='outro.novainfo.com.br').status_code, 404)
