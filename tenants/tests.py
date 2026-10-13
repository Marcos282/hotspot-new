from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from tenants.models import Tenant, TenantMembership, TenantSettings


@override_settings(DEBUG=True, ALLOWED_HOSTS=[".novainfo.com.br", "testserver"])
class TenantIsolationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant_a = Tenant.objects.create(name="Restaurante A", slug="restaurante-a")
        cls.tenant_b = Tenant.objects.create(name="Hotel B", slug="hotel-b")
        cls.user_a = get_user_model().objects.create_user(
            username="user-a", password="secure-test-password"
        )
        cls.user_b = get_user_model().objects.create_user(
            username="user-b", password="secure-test-password"
        )
        TenantMembership.objects.create(
            tenant=cls.tenant_a, user=cls.user_a, role=TenantMembership.Role.OWNER
        )
        TenantMembership.objects.create(
            tenant=cls.tenant_b, user=cls.user_b, role=TenantMembership.Role.OWNER
        )
        TenantSettings.objects.create(tenant=cls.tenant_a, display_name="Configuração A")
        TenantSettings.objects.create(tenant=cls.tenant_b, display_name="Configuração B")

    def test_tenant_is_resolved_from_subdomain(self):
        response = self.client.get(
            reverse("tenants:dashboard"), HTTP_HOST="restaurante-a.novainfo.com.br"
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_member_can_open_own_tenant_dashboard(self):
        self.client.force_login(self.user_a)
        response = self.client.get(
            reverse("tenants:dashboard"), HTTP_HOST="restaurante-a.novainfo.com.br"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Restaurante A")

    def test_member_cannot_open_another_tenant_dashboard(self):
        self.client.force_login(self.user_a)
        response = self.client.get(
            reverse("tenants:dashboard"), HTTP_HOST="hotel-b.novainfo.com.br"
        )
        self.assertEqual(response.status_code, 404)

    def test_user_without_membership_gets_not_found(self):
        user = get_user_model().objects.create_user(
            username="unrelated", password="secure-test-password"
        )
        self.client.force_login(user)
        response = self.client.get(
            reverse("tenants:dashboard"), HTTP_HOST="restaurante-a.novainfo.com.br"
        )
        self.assertEqual(response.status_code, 404)

    def test_unknown_and_inactive_tenants_are_not_resolved(self):
        inactive = Tenant.objects.create(
            name="Inativo", slug="inativo", is_active=False
        )
        for host in ("nao-existe.novainfo.com.br", f"{inactive.slug}.novainfo.com.br"):
            response = self.client.get(
                reverse("tenants:dashboard"), HTTP_HOST=host
            )
            self.assertEqual(response.status_code, 404)

    def test_nested_subdomains_are_not_tenant_hosts(self):
        response = self.client.get(
            reverse("tenants:dashboard"),
            HTTP_HOST="branch.restaurante-a.novainfo.com.br",
        )
        self.assertEqual(response.status_code, 404)

    def test_tenant_scoped_queryset_only_returns_requested_tenant(self):
        settings_for_a = TenantSettings.objects.for_tenant(self.tenant_a)
        self.assertEqual(list(settings_for_a), [self.tenant_a.settings])
        self.assertFalse(settings_for_a.filter(tenant=self.tenant_b).exists())

    def test_tenant_scoped_queryset_rejects_missing_tenant(self):
        with self.assertRaises(ValueError):
            TenantSettings.objects.for_tenant(None)

    def test_reserved_and_malformed_subdomains_are_rejected(self):
        for slug in ("gestao", "contains.dot", "-invalid", "invalid-"):
            with self.subTest(slug=slug), self.assertRaises(ValidationError):
                Tenant.objects.create(name="Inválido", slug=slug)

    def test_uppercase_subdomain_is_normalized(self):
        tenant = Tenant.objects.create(name="Caixa Alta", slug="Loja-A")
        self.assertEqual(tenant.slug, "loja-a")


@override_settings(DEBUG=True, ALLOWED_HOSTS=['.novainfo.com.br', 'testserver'])
class TenantPanelTests(TenantIsolationTests):
    def test_create_plan_ignores_posted_tenant(self):
        from tenants.models import AccessPlan, AuditEvent
        self.client.force_login(self.user_a)
        response = self.client.post('/painel/planos/novo/', {'name':'Plano A', 'duration_minutes':60, 'price':'3.00', 'tenant': self.tenant_b.pk, 'enabled':'on'}, HTTP_HOST='restaurante-a.novainfo.com.br')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(AccessPlan.objects.get().tenant_id, self.tenant_a.pk)
        self.assertEqual(AuditEvent.objects.get().tenant_id, self.tenant_a.pk)

    def test_cross_tenant_edit_is_denied(self):
        from tenants.models import AccessPlan
        plan = AccessPlan.objects.create(tenant=self.tenant_b, name='Segredo B', duration_minutes=60, price=3)
        self.client.force_login(self.user_a)
        response = self.client.post(f'/painel/planos/{plan.pk}/editar/', {'name':'Alterado', 'duration_minutes':60, 'price':'3.00'}, HTTP_HOST='restaurante-a.novainfo.com.br')
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(self.client.get('/painel/planos/', HTTP_HOST='restaurante-a.novainfo.com.br'), 'Segredo B')
        plan.refresh_from_db()
        self.assertEqual(plan.name, 'Segredo B')

    def test_viewer_cannot_write_or_read_sensitive_logs(self):
        TenantMembership.objects.filter(user=self.user_a).update(role='viewer')
        self.client.force_login(self.user_a)
        for url in ['/painel/planos/novo/', '/painel/hotspot/', '/painel/imagens/', '/painel/registros/', '/painel/auditoria/']:
            self.assertEqual(self.client.get(url, HTTP_HOST='restaurante-a.novainfo.com.br').status_code, 403)

    def test_root_account_redirects_to_tenant_login(self):
        response = self.client.post('/minha-conta/', {'slug': 'marcos'}, HTTP_HOST='novainfo.com.br')
        self.assertEqual(response['Location'], 'http://marcos.novainfo.com.br/accounts/login/')
        response = self.client.post('/minha-conta/', {'slug':'example.com/evil'}, HTTP_HOST='novainfo.com.br')
        self.assertEqual(response.status_code, 200)

    def test_wrong_workspace_login_is_rejected(self):
        response = self.client.post('/accounts/login/', {'username':'user-a', 'password':'secure-test-password'}, HTTP_HOST='hotel-b.novainfo.com.br')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_image_is_private_and_invalid_upload_rejected(self):
        from tenants.models import BrandImage
        from django.core.files.uploadedfile import SimpleUploadedFile
        image = BrandImage.objects.create(tenant=self.tenant_b, title='B', kind='logo', data=b'private')
        self.client.force_login(self.user_a)
        self.assertEqual(self.client.get(f'/painel/imagens/{image.pk}/', HTTP_HOST='restaurante-a.novainfo.com.br').status_code,404)
        response = self.client.post('/painel/imagens/', {'kind':'logo', 'title':'bad', 'image':SimpleUploadedFile('test.png', b'<script>bad</script>')}, HTTP_HOST='restaurante-a.novainfo.com.br')
        self.assertEqual(response.status_code,200)
        self.assertEqual(BrandImage.objects.count(),1)

    def test_online_requires_recent_heartbeat(self):
        from tenants.models import Device, AccessSession
        from django.utils import timezone
        from datetime import timedelta
        device = Device.objects.create(tenant=self.tenant_a,name='R',management_ip='10.0.0.2')
        AccessSession.objects.create(tenant=self.tenant_a,device=device,username='stale',started_at=timezone.now(),last_seen=timezone.now()-timedelta(hours=1))
        self.client.force_login(self.user_a)
        response = self.client.get('/painel/online/', HTTP_HOST='restaurante-a.novainfo.com.br')
        self.assertNotContains(response,'stale')

    def test_negative_price_and_public_management_ip_are_rejected(self):
        from tenants.forms import AccessPlanForm, DeviceForm
        self.assertFalse(AccessPlanForm({'name':'X','duration_minutes':0,'price':-1}).is_valid())
        self.assertFalse(DeviceForm({'name':'X','management_ip':'8.8.8.8'}).is_valid())


from unittest import skipUnless
from django.db import connection, transaction, DatabaseError
from django.test import TransactionTestCase


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL RLS')
class PostgreSQLIsolationTests(TransactionTestCase):
    def setUp(self):
        from tenants.models import AccessPlan
        self.a = Tenant.objects.create(name='A', slug='a')
        self.b = Tenant.objects.create(name='B', slug='b')
        self.user = get_user_model().objects.create_user(username='rls-user')
        TenantMembership.objects.create(tenant=self.a, user=self.user, role='owner')
        self.plan_a = AccessPlan.objects.create(tenant=self.a, name='A', price=3, duration_minutes=60)
        self.plan_b = AccessPlan.objects.create(tenant=self.b, name='B', price=3, duration_minutes=60)
        with connection.cursor() as cursor:
            cursor.execute('SELECT rolsuper FROM pg_roles WHERE rolname=current_user')
            if not cursor.fetchone()[0]:
                self.skipTest('Test setup requires an isolated migration role able to SET ROLE')
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname='novainfo_test_runtime'")
            if not cursor.fetchone():
                cursor.execute('CREATE ROLE novainfo_test_runtime NOSUPERUSER NOBYPASSRLS')
            cursor.execute('GRANT USAGE ON SCHEMA public TO novainfo_test_runtime')
            cursor.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO novainfo_test_runtime')
            cursor.execute('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO novainfo_test_runtime')

    def runtime(self):
        from contextlib import contextmanager
        @contextmanager
        def scope():
            with connection.cursor() as cursor:
                cursor.execute('SET ROLE novainfo_test_runtime')
            try:
                yield
            finally:
                with connection.cursor() as cursor:
                    cursor.execute('RESET ROLE')
        return scope()

    def test_unfiltered_select_update_delete_are_isolated(self):
        from tenants.models import AccessPlan
        from tenants.db_context import tenant_database_context
        with self.runtime(), tenant_database_context(self.a.pk, self.user.pk):
            self.assertEqual(list(AccessPlan.objects.values_list('name',flat=True)), ['A'])
            self.assertEqual(AccessPlan.objects.filter(pk=self.plan_b.pk).update(name='tampered'),0)
            self.assertEqual(AccessPlan.objects.filter(pk=self.plan_b.pk).delete()[0],0)

    def test_no_context_returns_no_data(self):
        from tenants.models import AccessPlan
        with self.runtime():
            self.assertEqual(AccessPlan.objects.count(),0)

    def test_forged_tenant_context_without_membership_is_denied(self):
        from tenants.models import AccessPlan
        from tenants.db_context import tenant_database_context
        with self.runtime(), tenant_database_context(self.b.pk,self.user.pk):
            self.assertEqual(AccessPlan.objects.count(),0)

    def test_cross_tenant_insert_and_relation_are_rejected(self):
        from tenants.models import AccessPlan, Sale
        from tenants.db_context import tenant_database_context
        with self.runtime(), tenant_database_context(self.a.pk,self.user.pk):
            with self.assertRaises(DatabaseError), transaction.atomic():
                AccessPlan.objects.create(tenant=self.b,name='bad',price=3,duration_minutes=60)
            with self.assertRaises(DatabaseError), transaction.atomic():
                Sale.objects.create(tenant=self.a,plan=self.plan_b,reference='bad',amount=3)

    def test_context_is_cleared_and_production_role_is_checked(self):
        from tenants.db_context import tenant_database_context
        from tenants.models import AccessPlan
        from tenants.checks import verify_runtime_database
        from django.core.exceptions import ImproperlyConfigured
        with override_settings(DEBUG=False):
            with self.assertRaises(ImproperlyConfigured):
                verify_runtime_database()
            with self.runtime():
                verify_runtime_database()
                with tenant_database_context(self.a.pk,self.user.pk):
                    self.assertEqual(AccessPlan.objects.count(),1)
                self.assertEqual(AccessPlan.objects.count(),0)
