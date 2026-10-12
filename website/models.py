from django.db import models


class LeadRequest(models.Model):
    name = models.CharField("nome", max_length=120)
    business_name = models.CharField("estabelecimento", max_length=150)
    email = models.EmailField("e-mail")
    phone = models.CharField("WhatsApp ou telefone", max_length=32, blank=True)
    message = models.CharField("mensagem", max_length=1000, blank=True)
    created_at = models.DateTimeField("recebido em", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "solicitação de demonstração"
        verbose_name_plural = "solicitações de demonstração"

    def __str__(self):
        return f"{self.business_name} — {self.name}"
