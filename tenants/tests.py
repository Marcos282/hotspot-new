from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from tenants.models import Tenant, TenantMembership, TenantSettings


@override_settings(ALLOWED_HOSTS=[".novainfo.com.br", "testserver"])
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
