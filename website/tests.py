from django.test import TestCase, override_settings
from django.urls import reverse

from website.models import LeadRequest


@override_settings(DEBUG=True)
class PublicWebsiteTests(TestCase):
    def test_homepage_shows_service_overview(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Transforme seu Wi-Fi")
        self.assertContains(response, "MikroTik")
        self.assertContains(response, "WireGuard")
        self.assertContains(response, "RADIUS")
        self.assertContains(response, "PRÉVIA CONCEITUAL")

    def test_demo_request_is_saved(self):
        response = self.client.post(
            reverse("demo-request"),
            {
                "name": "Ana Silva",
                "business_name": "Café Central",
                "email": "ana@example.com",
                "phone": "",
                "message": "Quero conhecer a solução.",
                "website": "",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Solicitação recebida")
        self.assertEqual(LeadRequest.objects.count(), 1)
        self.assertEqual(
            LeadRequest.objects.get().business_name,
            "Café Central",
        )

    def test_demo_request_rejects_honeypot_submission(self):
        response = self.client.post(
            reverse("demo-request"),
            {
                "name": "Bot",
                "business_name": "Spam",
                "email": "bot@example.com",
                "website": "https://spam.example",
            },
        )
        self.assertRedirects(response, "/#contato")
        self.assertEqual(LeadRequest.objects.count(), 0)

    def test_demo_request_requires_valid_email(self):
        response = self.client.post(
            reverse("demo-request"),
            {
                "name": "Ana Silva",
                "business_name": "Café Central",
                "email": "invalido",
                "website": "",
            },
        )
        self.assertRedirects(response, "/#contato")
        self.assertEqual(LeadRequest.objects.count(), 0)


@override_settings(DEBUG=True)
class CommercialWebsiteTests(TestCase):
    def test_plans_only_show_published_entries(self):
        from website.models import SubscriptionPlan
        SubscriptionPlan.objects.create(name="Plano oculto", description="Interno", is_active=False)
        plan = SubscriptionPlan.objects.get_or_create(name="Starter", defaults={"description": "Plano de teste"})[0]
        plan.monthly_price = "89.90"
        plan.save()
        response = self.client.get(reverse("platform-plans"))
        self.assertContains(response, "Starter")
        self.assertContains(response, "89,90")
        self.assertNotContains(response, "Plano oculto")

    def test_public_documents_and_sitemap(self):
        import xml.etree.ElementTree as ET
        for route in ["privacy", "terms", "retention", "platform-plans", "robots", "sitemap"]:
            self.assertEqual(self.client.get(reverse(route)).status_code, 200)
        xml = ET.fromstring(self.client.get(reverse("sitemap")).content)
        self.assertEqual(len(xml), 5)
        self.assertContains(self.client.get(reverse("robots")), "Disallow: /painel/")

    def test_demo_form_enforces_csrf(self):
        from django.test import Client
        response = Client(enforce_csrf_checks=True).post(reverse("demo-request"), {"name": "Ana"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(LeadRequest.objects.count(), 0)
