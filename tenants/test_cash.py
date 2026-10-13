from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase,override_settings
from django.core import signing
from tenants.models import Tenant,TenantMembership,AccessPlan,Sale,Payment,AuditEvent
from tenants.cash import CashSaleForm


@override_settings(DEBUG=True,ALLOWED_HOSTS=['.novainfo.com.br','testserver'])
class CashSaleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a=Tenant.objects.create(name='A',slug='a')
        cls.b=Tenant.objects.create(name='B',slug='b')
        cls.user=get_user_model().objects.create_user(username='cashier')
        TenantMembership.objects.create(tenant=cls.a,user=cls.user,role='staff')
        cls.plan=AccessPlan.objects.create(tenant=cls.a,name='Uma hora',duration_minutes=60,price='3.00')
        cls.other_plan=AccessPlan.objects.create(tenant=cls.b,name='Privado B',duration_minutes=120,price='9.00')

    def setUp(self):
        self.client.force_login(self.user)
        self.token=CashSaleForm(tenant=self.a,user=self.user).initial['request_token']

    def post(self,**overrides):
        payload={'plan':self.plan.pk,'received':'on','request_token':self.token}
        payload.update(overrides)
        return self.client.post('/painel/vendas/dinheiro/',payload,HTTP_HOST='a.novainfo.com.br')

    def test_cash_belongs_to_establishment_and_does_not_call_mercado_pago(self):
        with patch('operations.billing.api_request') as api:
            response=self.post(tenant=self.b.pk,amount='0.01',received_by=999)
            api.assert_not_called()
        self.assertEqual(response.status_code,302)
        sale=Sale.objects.get()
        payment=Payment.objects.get()
        self.assertEqual(sale.tenant_id,self.a.pk)
        self.assertEqual(str(sale.amount),'3.00')
        self.assertEqual(sale.duration_minutes,60)
        self.assertEqual(payment.method,'cash')
        self.assertEqual(payment.received_by_id,self.user.pk)
        self.assertIsNotNone(payment.received_at)
        self.assertEqual(AuditEvent.objects.get().actor_id,self.user.pk)

    def test_duplicate_submission_creates_only_one_receipt(self):
        self.post()
        self.post()
        self.assertEqual(Sale.objects.count(),1)
        self.assertEqual(Payment.objects.count(),1)
        self.assertEqual(AuditEvent.objects.count(),1)

    def test_foreign_plan_is_rejected(self):
        self.assertEqual(self.post(plan=self.other_plan.pk).status_code,200)
        self.assertEqual(Sale.objects.count(),0)
        self.assertNotContains(self.client.get('/painel/vendas/dinheiro/',HTTP_HOST='a.novainfo.com.br'),'Privado B')

    def test_viewer_cannot_register_cash(self):
        TenantMembership.objects.filter(user=self.user).update(role='viewer')
        self.assertEqual(self.post().status_code,403)
        self.assertEqual(Sale.objects.count(),0)

    def test_confirmation_required_and_tampered_token_rejected(self):
        self.assertEqual(self.post(received='').status_code,200)
        self.assertEqual(self.post(request_token='forged').status_code,200)
        self.assertEqual(Sale.objects.count(),0)

    def test_changed_price_and_duration_need_new_confirmation(self):
        AccessPlan.objects.filter(pk=self.plan.pk).update(price='6.00',duration_minutes=90)
        self.assertEqual(self.post().status_code,200)
        self.assertEqual(Sale.objects.count(),0)

    def test_sale_snapshot_survives_plan_changes(self):
        self.post()
        AccessPlan.objects.filter(pk=self.plan.pk).update(price='8.00',duration_minutes=240)
        sale=Sale.objects.get()
        self.assertEqual(str(sale.amount),'3.00')
        self.assertEqual(sale.duration_minutes,60)
        self.assertContains(self.client.get('/painel/pagamentos/',HTTP_HOST='a.novainfo.com.br'),'Dinheiro')

    def test_audit_failure_rolls_back_sale_and_payment(self):
        with patch('tenants.cash.AuditEvent.objects.create',side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):
                self.post()
        self.assertEqual(Sale.objects.count(),0)
        self.assertEqual(Payment.objects.count(),0)
