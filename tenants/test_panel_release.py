from decimal import Decimal
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase,override_settings,Client
from tenants.models import Tenant,TenantMembership,Device,AccessPlan,HotspotAccess
from tenants.panel_forms import HotspotAccessForm
from tenants.forms import AccessPlanForm
from operations.models import WireGuardPeer
from operations.routeros import RouterOSError


@override_settings(DEBUG=True,ALLOWED_HOSTS=['testserver','.novainfo.com.br'])
class PanelReleaseTests(TestCase):
    def setUp(self):
        self.a=Tenant.objects.create(name='Pousada A',slug='panel-a')
        self.b=Tenant.objects.create(name='Pousada B',slug='panel-b')
        self.user=get_user_model().objects.create_user(username='reception',password='test-password')
        self.member=TenantMembership.objects.create(tenant=self.a,user=self.user,role='owner')
        self.device=Device.objects.create(tenant=self.a,name='Router A',management_ip='10.77.0.2',session_collection_enabled=True,privacy_purpose='Test')
        self.foreign=Device.objects.create(tenant=self.b,name='SECRET ROUTER B',management_ip='10.77.0.3')
        self.plan=AccessPlan.objects.create(tenant=self.a,name='Plano 3h',duration_minutes=180,price=Decimal('10.50'))
        self.other=AccessPlan.objects.create(tenant=self.b,name='SECRET PLAN B',duration_minutes=60,price=Decimal('20.00'))
        self.client.force_login(self.user)

    def get(self,path):
        return self.client.get(path,HTTP_HOST='panel-a.novainfo.com.br')

    def post(self,**extra):
        data={'guest_name':'João','username':'joao-12','password':'WiFi-password-42','plan':self.plan.pk,'device':self.device.pk,'devices':3,
              'request_token':HotspotAccessForm(tenant=self.a,user=self.user).initial['request_token']}
        data.update(extra)
        return self.client.post('/painel/criar-acesso/',data,HTTP_HOST='panel-a.novainfo.com.br')

    def test_clean_navigation_and_removed_admin_activity(self):
        response=self.get('/painel/')
        for label in ['Início','Usuários Online','Criar Acesso','Personalizar Hotspot','Minha Conta','Pagamento']:
            self.assertContains(response,label)
        self.assertContains(response,'tenant/clean.css')
        self.assertNotContains(response,'Atividades administrativas')
        self.assertNotContains(response,'Minha assinatura Nova Info')

    def test_price_accepts_comma_dot_and_integer(self):
        for value,expected in [('10','10.00'),('10,50','10.50'),('10.50','10.50'),('R$ 1.234,56','1234.56')]:
            form=AccessPlanForm({'name':'Test','duration_minutes':60,'price':value,'speed_limit':'5M/10M','enabled':'on'})
            self.assertTrue(form.is_valid(),form.errors)
            self.assertEqual(form.cleaned_data['price'],Decimal(expected))
            self.assertEqual(form.fields['price'].widget.input_type,'text')
        for value in ['-1','1,234','abc','NaN','1.2.3']:
            form=AccessPlanForm({'name':'Test','duration_minutes':60,'price':value})
            self.assertFalse(form.is_valid())

    def test_plan_durations(self):
        for minutes in [60,180,360]:
            self.assertTrue(AccessPlanForm({'name':'Test','duration_minutes':minutes,'price':'10,50'}).is_valid())
        self.assertFalse(AccessPlanForm({'name':'Test','duration_minutes':120,'price':'10,50'}).is_valid())

    @patch('tenants.hotspot_service.connected_client')
    def test_chosen_credentials_limits_and_idempotency(self,connection):
        client=connection.return_value.__enter__.return_value
        client.read.return_value=[{'uptime':'1d'}]
        form=HotspotAccessForm(tenant=self.a,user=self.user)
        token=form.initial['request_token']
        response=self.post(request_token=token)
        self.assertContains(response,'O MikroTik confirmou')
        access=HotspotAccess.objects.get()
        self.assertEqual(access.tenant_id,self.a.pk)
        self.assertEqual(access.duration_minutes,180)
        self.assertEqual(access.devices,3)
        self.assertEqual(access.username,'joao-12')
        self.assertNotEqual(access.encrypted_password,'WiFi-password-42')
        self.assertContains(response,'https://wa.me/')
        self.assertIn('no-store',response['Cache-Control'])
        self.post(request_token=token)
        self.assertEqual(HotspotAccess.objects.count(),1)
        self.assertEqual(client.create_access.call_count,1)

    @patch('tenants.hotspot_service.connected_client')
    def test_foreign_device_and_plan_rejected(self,connection):
        self.post(device=self.foreign.pk)
        self.post(plan=self.other.pk)
        connection.assert_not_called()
        response=self.get('/painel/criar-acesso/')
        self.assertNotContains(response,'SECRET ROUTER B')
        self.assertNotContains(response,'SECRET PLAN B')

    @patch('tenants.hotspot_service.connected_client')
    def test_limits_and_viewer_permissions(self,connection):
        for devices in [0,7]:
            self.assertContains(self.post(devices=devices),'errorlist')
        connection.assert_not_called()
        self.member.role='viewer'
        self.member.save()
        self.assertEqual(self.get('/painel/criar-acesso/').status_code,403)

    @patch('tenants.hotspot_service.connected_client')
    def test_timeout_marks_uncertain_and_does_not_repeat(self,connection):
        client=connection.return_value.__enter__.return_value
        client.read.return_value=[{'uptime':'1d'}]
        client.create_access.side_effect=RouterOSError()
        token=HotspotAccessForm(tenant=self.a,user=self.user).initial['request_token']
        self.post(request_token=token)
        self.post(request_token=token)
        self.assertEqual(HotspotAccess.objects.get().status,'uncertain')
        self.assertEqual(client.create_access.call_count,1)

    @patch('tenants.panel_views.connected_client')
    def test_online_no_stale_fallback_and_no_foreign_device(self,connection):
        client=connection.return_value.__enter__.return_value
        client.read.return_value=[{'user':'guest-online','address':'10.5.50.10','uptime':'5m'}]
        response=self.get('/painel/usuarios-online/')
        self.assertContains(response,'guest-online')
        self.assertEqual(connection.call_args.args[0].tenant_id,self.a.pk)
        connection.side_effect=RouterOSError()
        response=self.get('/painel/usuarios-online/')
        self.assertContains(response,'MikroTik desconectado')
        self.assertNotContains(response,'guest-online')
        self.assertIn('no-store',response['Cache-Control'])

    def test_csrf_not_disabled(self):
        client=Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post('/painel/criar-acesso/',{},HTTP_HOST='panel-a.novainfo.com.br').status_code,403)

    def test_https_post_through_nginx_keeps_csrf_checks(self):
        client=Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response=client.get('/painel/planos/novo/',HTTP_HOST='panel-a.novainfo.com.br',HTTP_X_FORWARDED_PROTO='https')
        token=client.cookies['csrftoken'].value
        data={'name':'One hour','duration_minutes':'60','price':'10,50','csrfmiddlewaretoken':token}
        response=client.post('/painel/planos/novo/',data,HTTP_HOST='panel-a.novainfo.com.br',HTTP_X_FORWARDED_PROTO='https',HTTP_ORIGIN='https://panel-a.novainfo.com.br')
        self.assertEqual(response.status_code,302)
        response=client.post('/painel/planos/novo/',data,HTTP_HOST='panel-a.novainfo.com.br',HTTP_X_FORWARDED_PROTO='https',HTTP_ORIGIN='https://panel-b.novainfo.com.br')
        self.assertEqual(response.status_code,403)

    def test_postgresql_new_access_table_has_real_rls(self):
        import uuid
        from django.db import connection,transaction,DatabaseError
        from tenants.db_context import tenant_database_context
        if connection.vendor!='postgresql':
            self.skipTest('Exige PostgreSQL.')
        access=HotspotAccess.objects.create(tenant=self.a,device=self.device,plan=self.plan,created_by=self.user,guest_name='Private',username='rls-private',encrypted_password='test',devices=1,duration_minutes=60,request_id=uuid.uuid4())
        role='release_rls_'+uuid.uuid4().hex[:12]
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE ROLE {role} NOSUPERUSER NOBYPASSRLS')
            cursor.execute(f'GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {role}')
            cursor.execute(f'GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}')
            cursor.execute(f'SET LOCAL ROLE {role}')
        try:
            self.assertEqual(HotspotAccess.objects.count(),0)
            with tenant_database_context(self.a.pk,self.user.pk):
                self.assertEqual(HotspotAccess.objects.get().pk,access.pk)
                with self.assertRaises(DatabaseError),transaction.atomic():
                    HotspotAccess.objects.create(tenant=self.b,device=self.foreign,plan=self.other,created_by=self.user,guest_name='forged',username='forged',encrypted_password='test',devices=1,duration_minutes=60,request_id=uuid.uuid4())
            with tenant_database_context(self.b.pk,self.user.pk):
                self.assertEqual(HotspotAccess.objects.count(),0)
        finally:
            with connection.cursor() as cursor:
                cursor.execute('RESET ROLE')


    def test_centrally_registered_device_visible_only_to_its_tenant(self):
        response=self.get('/painel/')
        self.assertContains(response,'MikroTik do estabelecimento')
        self.assertContains(response,'Router A')
        self.assertContains(response,'10.77.0.2')
        self.assertNotContains(response,'SECRET ROUTER B')
        self.assertNotContains(response,'10.77.0.3')
        response=self.get('/painel/equipamentos/')
        self.assertContains(response,'Router A')
        self.assertNotContains(response,'SECRET ROUTER B')
        response=self.get('/painel/criar-acesso/')
        self.assertEqual(response.context['form'].initial['device'],self.device.pk)
        self.assertContains(response,'Router A')
        self.assertNotContains(response,'SECRET ROUTER B')
