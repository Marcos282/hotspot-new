import base64
import hashlib
import hmac
import os
from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone
from cryptography.fernet import Fernet
from tenants.models import Tenant, TenantMembership, Device, AccessPlan, Sale, Payment, AccessSession, AuditEvent
from operations.models import NetworkConfiguration, WireGuardPeer, DeviceHealth, HealthSample, Outage, DeviceAlert
from operations.wireguard import allocate_peer, routeros_script, server_configuration, apply_peer, WireGuardError
from operations.monitoring import probe_device, monthly_availability
from operations.security import encrypt_secret, decrypt_secret
from operations.mercadopago import verify_webhook, PaymentIntegrationError


@override_settings(DEBUG=True,ALLOWED_HOSTS=['testserver','.novainfo.com.br'])
class CentralTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin=get_user_model().objects.create_superuser(username='central',email='central@example.com',password='test-password')
        cls.owner=get_user_model().objects.create_user(username='owner',password='test-password')
        cls.a=Tenant.objects.create(name='A',slug='a')
        cls.b=Tenant.objects.create(name='B',slug='b')
        TenantMembership.objects.create(tenant=cls.a,user=cls.owner,role='owner')
        cls.device=Device.objects.create(tenant=cls.a,name='Router A',management_ip='10.77.0.2',routeros_version='7.20',monitoring_enabled=True)
        cls.config=NetworkConfiguration.objects.create(endpoint='vpn.novainfo.com.br',public_key=base64.b64encode(b'A'*32).decode())

    def login(self):
        self.client.force_login(self.admin)

    def test_central_denies_tenant_owner_and_subdomain(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get('/central/').status_code,403)
        self.login()
        self.assertEqual(self.client.get('/central/',HTTP_HOST='a.novainfo.com.br').status_code,403)

    def test_all_central_pages_render_without_fictitious_online_data(self):
        self.login()
        for path in ['/central/','/central/configuracoes/','/central/estabelecimentos/','/central/equipamentos/','/central/usuarios/','/central/wireguard/','/central/wireguard/novo/','/central/conexoes/','/central/relatorios/','/central/planos/','/central/hotspot/','/central/publicidade/','/central/auditoria/']:
            response=self.client.get(path)
            self.assertEqual(response.status_code,200,path)
        self.assertContains(self.client.get('/central/'),'Aguardando configuração')

    def test_create_establishment_is_audited(self):
        self.login()
        response=self.client.post('/central/estabelecimentos/novo/',{'name':'Hotel','slug':'hotel','is_active':'on'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(AuditEvent.objects.get().fields_changed,['name','slug'])

    def test_ip_allocation_and_duplicate_reservations(self):
        peer=allocate_peer(self.device,base64.b64encode(b'B'*32).decode())
        self.assertEqual(peer.vpn_ip,'10.77.0.2')
        other=Device.objects.create(tenant=self.b,name='B',management_ip='10.77.0.3')
        with self.assertRaises(ValidationError):
            allocate_peer(other,base64.b64encode(b'C'*32).decode(),'10.77.0.2')
        peer.enabled=False
        peer.save()
        new=allocate_peer(other,base64.b64encode(b'C'*32).decode())
        self.assertEqual(new.vpn_ip,'10.77.0.3')

    def test_version_specific_scripts_and_no_overwrite(self):
        peer=allocate_peer(self.device,base64.b64encode(b'B'*32).decode())
        script=routeros_script(peer,self.config)
        self.assertIn(':error',script)
        self.assertNotIn('/ip service set',script.split('# Alterações')[0])
        self.assertNotIn('private-key=',script)
        self.device.routeros_version='6.49.18'
        self.assertIn('não oferece WireGuard nativo',routeros_script(peer,self.config))
        self.assertNotIn('/interface wireguard peers add',routeros_script(peer,self.config))
        with patch('operations.wireguard.snapshot',return_value=({}, {peer.public_key:[]})), patch('operations.wireguard.command') as command:
            with self.assertRaises(WireGuardError):
                apply_peer(peer)
            command.assert_not_called()

    def test_revocation_does_not_claim_live_removal(self):
        peer=allocate_peer(self.device,base64.b64encode(b'B'*32).decode())
        self.login()
        self.assertEqual(self.client.get(f'/central/wireguard/{peer.pk}/revogar/').status_code,405)
        self.client.post(f'/central/wireguard/{peer.pk}/revogar/')
        peer.refresh_from_db()
        self.assertFalse(peer.enabled)
        self.assertIsNone(peer.removal_confirmed_at)
        self.assertIn('pendente',peer.lifecycle_label)

    @override_settings(ROUTEROS_CREDENTIAL_KEY=Fernet.generate_key().decode())
    def test_credential_is_encrypted_and_audit_has_no_secret(self):
        from operations.forms import CentralDeviceForm
        form=CentralDeviceForm({'tenant':self.a.pk,'name':'Router A','management_ip':'10.77.0.2','routeros_version':'7.20','api_username':'nova-reader','api_password':'secret-test'},instance=self.device)
        self.assertTrue(form.is_valid(),form.errors)
        obj=form.save()
        self.assertNotIn('secret-test',obj.api_password_encrypted)
        self.assertEqual(decrypt_secret(obj.api_password_encrypted),'secret-test')
        self.assertNotIn('secret-test',str(form['api_password']))

    def test_missing_wireguard_data_is_unknown_and_not_alerted(self):
        allocate_peer(self.device,base64.b64encode(b'B'*32).decode())
        health=probe_device(self.device,self.config,None)
        self.assertEqual(health.vpn_status,'unknown')
        self.assertEqual(DeviceAlert.objects.count(),0)
        self.assertEqual(Outage.objects.count(),0)

    def test_alert_is_deduplicated_and_recovery_recorded(self):
        peer=allocate_peer(self.device,base64.b64encode(b'B'*32).decode())
        from ipaddress import ip_network
        start=timezone.now()
        offline=({peer.public_key:0},{peer.public_key:[ip_network(peer.vpn_ip+'/32')]})
        for seconds in [0,301,601]:
            probe_device(self.device,self.config,offline,now=start+timedelta(seconds=seconds))
        self.assertEqual(DeviceAlert.objects.count(),1)
        self.assertEqual(Outage.objects.count(),1)
        online=({peer.public_key:int((start+timedelta(seconds=700)).timestamp())},{peer.public_key:[ip_network(peer.vpn_ip+'/32')]})
        probe_device(self.device,self.config,online,now=start+timedelta(seconds=700))
        self.assertIsNotNone(Outage.objects.get().ended_at)

    def test_api_and_vpn_are_independent(self):
        from ipaddress import ip_network
        peer=allocate_peer(self.device,base64.b64encode(b'B'*32).decode())
        self.device.api_username='reader'
        self.device.api_password_encrypted='configured'
        now=timezone.now()
        data=({peer.public_key:int(now.timestamp())},{peer.public_key:[ip_network(peer.vpn_ip+'/32')]})
        from operations.routeros import RouterOSError
        class FailedClient:
            def __init__(self,*args): pass
            def __enter__(self): raise RouterOSError('failed')
            def __exit__(self,*args): pass
        health=probe_device(self.device,self.config,data,now=now,client_class=FailedClient)
        self.assertEqual(health.vpn_status,'online')
        self.assertEqual(health.api_status,'offline')

    def test_hotspot_session_collection_requires_documented_purpose(self):
        from operations.forms import CentralDeviceForm
        form=CentralDeviceForm({'tenant':self.a.pk,'name':'Router A','management_ip':'10.77.0.2','session_collection_enabled':'on'},instance=self.device)
        self.assertFalse(form.is_valid())
        self.assertIn('privacy_purpose',form.errors)

    def test_unknown_periods_do_not_count_as_uptime(self):
        now=timezone.now().replace(day=10)
        HealthSample.objects.create(tenant=self.a,device=self.device,vpn_status='online',api_status='unknown',hotspot_status='unknown',checked_at=now-timedelta(hours=1))
        availability=monthly_availability(self.device,now)
        self.assertEqual(availability['coverage_seconds'],300)
        self.assertEqual(availability['vpn_percent'],100)
        self.assertIsNone(availability['api_percent'])
        self.assertLess(availability['month_coverage_percent'],1)

    def test_report_tenant_cannot_select_foreign_device(self):
        other=Device.objects.create(tenant=self.b,name='Foreign',management_ip='10.77.0.3')
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(f'/painel/relatorios/?device={other.pk}',HTTP_HOST='a.novainfo.com.br').status_code,404)

    def test_personal_session_and_brand_preview_pages_render(self):
        self.client.force_login(self.owner)
        for path in ['/painel/relatorios/','/painel/hotspot/previa/']:
            self.assertEqual(self.client.get(path,HTTP_HOST='a.novainfo.com.br').status_code,200)


@override_settings(DEBUG=True)
class MercadoPagoTests(TestCase):
    def test_signature_rejects_forgery_and_old_notifications(self):
        manifest='id:123;request-id:test-request;ts:1000;'
        signature='ts=1000,v1='+hmac.new(b'secret',manifest.encode(),hashlib.sha256).hexdigest()
        self.assertTrue(verify_webhook('123','test-request',signature,'secret',now=1000))
        self.assertFalse(verify_webhook('124','test-request',signature,'secret',now=1000))
        self.assertFalse(verify_webhook('123','test-request',signature,'secret',now=2000))

    def test_unconfigured_webhook_is_disabled(self):
        with patch.dict(os.environ,{'MERCADOPAGO_RECEIVER_MODE':''}):
            self.assertEqual(self.client.post('/integracoes/mercado-pago/assinaturas/webhook/').status_code,503)


from tenants.tests import PostgreSQLIsolationTests


class CentralPostgreSQLIsolationTests(PostgreSQLIsolationTests):
    def setUp(self):
        super().setUp()
        if self._outcome and not self._outcome.success:
            return
        from django.contrib.auth.models import Permission
        self.operator=get_user_model().objects.create_user(username='network-operator',is_staff=True)
        self.operator.user_permissions.add(Permission.objects.get(codename='manage_network',content_type__app_label='operations'))
        self.config=NetworkConfiguration.objects.create(endpoint='vpn.novainfo.com.br',public_key=base64.b64encode(b'A'*32).decode())
        self.device_a=Device.objects.create(tenant=self.a,name='A',management_ip='10.77.0.2')
        self.device_b=Device.objects.create(tenant=self.b,name='B',management_ip='10.77.0.3')
        HealthSample.objects.create(tenant=self.a,device=self.device_a,vpn_status='online',api_status='unknown',hotspot_status='unknown')
        HealthSample.objects.create(tenant=self.b,device=self.device_b,vpn_status='online',api_status='unknown',hotspot_status='unknown')

    def test_network_operator_context_can_read_all_tenants(self):
        from tenants.db_context import tenant_database_context
        with self.runtime(),tenant_database_context(None,self.operator.pk,central=True):
            self.assertEqual(Device.objects.count(),2)
            self.assertEqual(HealthSample.objects.count(),2)
            self.assertEqual(NetworkConfiguration.objects.count(),1)

    def test_tenant_cannot_read_foreign_monitoring_or_system_configuration(self):
        from tenants.db_context import tenant_database_context
        with self.runtime(),tenant_database_context(self.a.pk,self.user.pk):
            self.assertEqual(list(HealthSample.objects.values_list('tenant_id',flat=True)),[self.a.pk])
            self.assertEqual(NetworkConfiguration.objects.count(),0)

    def test_forged_central_flag_is_not_enough(self):
        from tenants.db_context import tenant_database_context
        with self.runtime(),tenant_database_context(None,self.user.pk,central=True):
            self.assertEqual(HealthSample.objects.count(),0)
            self.assertEqual(NetworkConfiguration.objects.count(),0)

    def test_peer_cross_tenant_device_is_rejected_by_database(self):
        from django.db import transaction,DatabaseError
        from tenants.db_context import tenant_database_context
        with self.runtime(),tenant_database_context(None,self.operator.pk,central=True):
            with self.assertRaises(DatabaseError),transaction.atomic():
                WireGuardPeer.objects.create(tenant=self.a,device=self.device_b,public_key=base64.b64encode(b'C'*32).decode(),vpn_ip='10.77.0.3')

    def test_central_permission_revocation_is_enforced_by_database(self):
        from tenants.db_context import tenant_database_context
        self.operator.user_permissions.clear()
        with self.runtime(),tenant_database_context(None,self.operator.pk,central=True):
            self.assertEqual(NetworkConfiguration.objects.count(),0)

    def test_registry_isolation_and_public_resolution_are_limited(self):
        from tenants.db_context import tenant_database_context
        from django.db import connection,transaction,DatabaseError
        with self.runtime(),tenant_database_context(self.a.pk,self.user.pk):
            self.assertEqual(list(Tenant.objects.values_list('pk',flat=True)),[self.a.pk])
            self.assertEqual(TenantMembership.objects.count(),1)
            with self.assertRaises(DatabaseError),transaction.atomic():
                Tenant.objects.create(name='Forbidden',slug='forbidden')
            with connection.cursor() as cursor:
                cursor.execute('SELECT * FROM public.novainfo_resolve_tenant(%s)',['b'])
                self.assertEqual([column[0] for column in cursor.description],['id','name','slug','is_active'])
                self.assertEqual(cursor.fetchone()[0],self.b.pk)

    @override_settings(DEBUG=True,ALLOWED_HOSTS=['.novainfo.com.br','testserver'])
    def test_http_tenant_and_central_contexts_with_runtime_role(self):
        self.client.force_login(self.user)
        with self.runtime():
            response=self.client.get('/painel/',HTTP_HOST='a.novainfo.com.br')
            self.assertEqual(response.status_code,200)
            self.assertEqual(self.client.get('/painel/',HTTP_HOST='b.novainfo.com.br').status_code,404)
        self.client.force_login(self.operator)
        with self.runtime():
            self.assertEqual(self.client.get('/central/').status_code,200)


    def test_subscription_request_price_and_status_are_protected_in_database(self):
        from tenants.db_context import tenant_database_context
        from operations.models import SaaSSubscription
        from website.models import SubscriptionPlan
        from django.db import transaction,DatabaseError
        plan=SubscriptionPlan.objects.get_or_create(name='Starter',defaults={'description':'Plano de teste'})[0]
        plan.monthly_price='89.90'
        plan.save()
        with self.runtime(),tenant_database_context(self.a.pk,self.user.pk):
            with self.assertRaises(DatabaseError),transaction.atomic():
                SaaSSubscription.objects.create(tenant=self.a,plan=plan,monthly_amount='1.00',payer_email='user@example.com',requested_by=self.user)
            subscription=SaaSSubscription.objects.create(tenant=self.a,plan=plan,monthly_amount='89.90',payer_email='user@example.com',requested_by=self.user)
            self.assertEqual(SaaSSubscription.objects.filter(pk=subscription.pk).update(status='authorized'),0)
            self.assertEqual(SaaSSubscription.objects.filter(pk=subscription.pk).update(monthly_amount='1.00'),0)
            self.assertEqual(SaaSSubscription.objects.get(pk=subscription.pk).status,'requested')


    @override_settings(DEBUG=True,ALLOWED_HOSTS=['.novainfo.com.br','testserver'])
    def test_cash_receipt_http_uses_runtime_isolation_and_no_provider(self):
        from tenants.db_context import tenant_database_context
        self.client.force_login(self.user)
        with self.runtime():
            response=self.client.get('/painel/vendas/dinheiro/',HTTP_HOST='a.novainfo.com.br')
            self.assertEqual(response.status_code,200)
            token=response.context['form'].initial['request_token']
            payload={'plan':self.plan_a.pk,'received':'on','request_token':token,'tenant':self.b.pk,'amount':'0.01'}
            with patch('operations.billing.api_request') as api:
                for repeat in range(2):
                    response=self.client.post('/painel/vendas/dinheiro/',payload,HTTP_HOST='a.novainfo.com.br')
                    self.assertEqual(response.status_code,302)
                api.assert_not_called()
            with tenant_database_context(self.a.pk,self.user.pk):
                self.assertEqual(Sale.objects.count(),1)
                payment=Payment.objects.get()
                self.assertEqual(payment.method,'cash')
                self.assertEqual(payment.received_by_id,self.user.pk)
                self.assertEqual(str(payment.amount),'3.00')
            with tenant_database_context(self.b.pk,self.user.pk):
                self.assertEqual(Payment.objects.count(),0)


@override_settings(DEBUG=True,ALLOWED_HOSTS=['.novainfo.com.br','testserver'])
class SaaSBillingTests(TestCase):
    def setUp(self):
        from website.models import SubscriptionPlan
        self.tenant=Tenant.objects.create(name='A',slug='a')
        self.owner=get_user_model().objects.create_user(username='owner')
        TenantMembership.objects.create(tenant=self.tenant,user=self.owner,role='owner')
        self.plan=SubscriptionPlan.objects.get_or_create(name='Starter',defaults={'description':'Plano de teste'})[0]
        self.plan.monthly_price='89.90'
        self.plan.save()
        self.client.force_login(self.owner)

    @patch.dict(os.environ,{'MERCADOPAGO_SUBSCRIPTIONS_ENABLED':'true','MERCADOPAGO_ACCESS_TOKEN':'test-token','MERCADOPAGO_WEBHOOK_SECRET':'test-secret','MERCADOPAGO_COLLECTOR_ID':'999'})
    def test_monthly_request_is_durable_and_does_not_call_provider_in_http(self):
        from operations.models import SaaSSubscription
        from django.core import signing
        quote=signing.dumps({str(self.plan.pk):'89.90'},salt='saas-quote')
        with patch('operations.billing.api_request') as api:
            response=self.client.post('/painel/assinatura/',{'plan':self.plan.pk,'payer_email':'owner@example.com','quote':quote,'authorize':'on'},HTTP_HOST='a.novainfo.com.br')
            api.assert_not_called()
        self.assertEqual(response.status_code,302)
        subscription=SaaSSubscription.objects.get()
        self.assertEqual(subscription.status,'requested')
        self.assertEqual(subscription.tenant_id,self.tenant.pk)
        self.assertEqual(str(subscription.monthly_amount),'89.90')

    def test_disabled_billing_renders_no_checkout(self):
        response=self.client.get('/painel/assinatura/',HTTP_HOST='a.novainfo.com.br')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'ainda não está habilitada')

    @patch.dict(os.environ,{'MERCADOPAGO_SUBSCRIPTIONS_ENABLED':'true','MERCADOPAGO_ACCESS_TOKEN':'test-token','MERCADOPAGO_WEBHOOK_SECRET':'test-secret','MERCADOPAGO_COLLECTOR_ID':'999'})
    def test_stale_price_is_rejected(self):
        from operations.models import SaaSSubscription
        from django.core import signing
        quote=signing.dumps({str(self.plan.pk):'39.90'},salt='saas-quote')
        response=self.client.post('/painel/assinatura/',{'plan':self.plan.pk,'payer_email':'owner@example.com','quote':quote,'authorize':'on'},HTTP_HOST='a.novainfo.com.br')
        self.assertEqual(response.status_code,200)
        self.assertFalse(SaaSSubscription.objects.exists())

    @patch.dict(os.environ,{'MERCADOPAGO_SUBSCRIPTIONS_ENABLED':'true','MERCADOPAGO_ACCESS_TOKEN':'test-token','MERCADOPAGO_WEBHOOK_SECRET':'test-secret','MERCADOPAGO_COLLECTOR_ID':'999'})
    def test_remote_authorization_does_not_mark_an_internet_sale_paid(self):
        from operations.models import SaaSSubscription
        from operations.billing import reconcile_subscription
        subscription=SaaSSubscription.objects.create(tenant=self.tenant,plan=self.plan,monthly_amount='89.90',payer_email='owner@example.com',requested_by=self.owner)
        response={'id':'abc123','collector_id':999,'external_reference':'ni-sub:'+str(subscription.external_id),'auto_recurring':{'frequency':1,'frequency_type':'months','transaction_amount':89.90,'currency_id':'BRL'},'status':'authorized'}
        with patch('operations.billing.api_request',return_value=response):
            reconcile_subscription('abc123',self.owner)
            reconcile_subscription('abc123',self.owner)
        subscription.refresh_from_db()
        self.assertEqual(subscription.status,'authorized')
        self.assertEqual(Payment.objects.count(),0)
        self.assertEqual(AuditEvent.objects.count(),1)
        response['auto_recurring']['transaction_amount']=1
        with patch('operations.billing.api_request',return_value=response),self.assertRaises(PaymentIntegrationError):
            reconcile_subscription('abc123',self.owner)
