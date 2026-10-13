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
