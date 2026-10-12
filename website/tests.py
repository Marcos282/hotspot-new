from django.test import TestCase
from django.urls import reverse

from website.models import LeadRequest


class PublicWebsiteTests(TestCase):
    def test_homepage_shows_service_overview(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Wi-Fi que trabalha")
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
