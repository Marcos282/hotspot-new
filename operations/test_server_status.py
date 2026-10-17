import json
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase
from operations.server_status import wireguard_server_status


class ServerStatusTests(SimpleTestCase):
    def check(self,changes=None,age=0):
        config=SimpleNamespace(interface='wg0',public_key='public',port=51820,server_ip='10.77.0.1')
        snapshot={'checked_at':(datetime.now(timezone.utc)-timedelta(seconds=age)).isoformat(),'interface':'wg0','public_key':'public','port':51820,'addresses':['10.77.0.1'],'active':True}
        snapshot.update(changes or {})
        with patch('operations.server_status.shutil.which',return_value='/usr/bin/wg'),patch('operations.server_status.Path.read_text',return_value=json.dumps(snapshot)):
            return wireguard_server_status(config)

    def test_verified_server_is_active(self):
        self.assertTrue(self.check()['active'])

    def test_stale_and_inactive_server_are_not_marked_active(self):
        self.assertFalse(self.check(age=200)['active'])
        self.assertFalse(self.check({'active':False})['active'])

    def test_different_identity_or_address_is_not_active(self):
        self.assertFalse(self.check({'public_key':'other'})['active'])
        self.assertFalse(self.check({'addresses':['10.8.0.1']})['active'])

    def test_missing_package_is_not_active(self):
        with patch('operations.server_status.shutil.which',return_value=None):
            result=wireguard_server_status(None)
        self.assertFalse(result['active'])
        self.assertEqual(result['label'],'Aguardando instalação')

    def test_details_are_available_but_stale_data_is_not_active(self):
        result = self.check({'service_state': 'active', 'service_substate': 'exited', 'mtu': 1420}, age=200)
        self.assertFalse(result['active'])
        self.assertEqual(result['observed']['service_substate'], 'exited')
        self.assertEqual(result['observed']['mtu'], 1420)
        self.assertNotIn('public_key', result['observed'])

    def test_malformed_snapshot_is_not_active(self):
        for content in ['[]', '{', '{"checked_at": "invalid"}']:
            with self.subTest(content=content), patch('operations.server_status.shutil.which', return_value='/usr/bin/wg'), patch('operations.server_status.Path.read_text', return_value=content):
                self.assertFalse(wireguard_server_status(None)['active'])


from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from tenants.models import Tenant


@override_settings(DEBUG=True)
class StatusPageTests(TestCase):
    def setUp(self):
        self.host = {'HTTP_HOST': 'novainfo.com.br'}
        self.admin = get_user_model().objects.create_user('status-admin', is_staff=True)
        self.admin.user_permissions.add(Permission.objects.get(codename='manage_network', content_type__app_label='operations'))

    def test_anonymous_needs_login(self):
        response = self.client.get('/central/status/', **self.host)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/painel/login/', response.url)

    def test_staff_without_permission_is_denied(self):
        user = get_user_model().objects.create_user('staff', is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get('/central/status/', **self.host).status_code, 403)

    def test_admin_sees_status_and_navigation(self):
        self.client.force_login(self.admin)
        with patch('operations.server_status.wireguard_server_status', return_value={
            'label': 'Ativo', 'detail': 'Verificado', 'observed': {
                'service_state': 'active', 'service_substate': 'exited',
                'mtu': 1420, 'received_bytes': 0, 'sent_bytes': 0,
            },
        }):
            response = self.client.get('/central/status/', **self.host)
        self.assertContains(response, 'active / exited')
        self.assertContains(response, '1420')
        self.assertContains(response, '0\u00a0byte')
        self.assertContains(response, '/central/status/')
        self.assertEqual(response['Cache-Control'], 'no-store')

    def test_admin_is_denied_on_tenant_host(self):
        Tenant.objects.create(name='Nessa', slug='nessa')
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get('/central/status/', HTTP_HOST='nessa.novainfo.com.br').status_code, 403)
