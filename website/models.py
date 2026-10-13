from django.db import models
from django.core.validators import MinValueValidator


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


class SubscriptionPlan(models.Model):
    name = models.CharField("nome", max_length=80, unique=True)
    description = models.TextField("descrição")
    features = models.TextField("recursos", blank=True, help_text="Um recurso por linha. Informe apenas recursos e disponibilidade confirmados.")
    monthly_price = models.DecimalField("valor mensal", max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    is_active = models.BooleanField("publicado", default=True)
    is_featured = models.BooleanField("destaque", default=False)
    position = models.PositiveIntegerField("ordem", default=0)

    class Meta:
        ordering = ["position", "pk"]
        verbose_name = "plano da plataforma"
        verbose_name_plural = "planos da plataforma"

    def __str__(self):
        return self.name

    @property
    def feature_list(self):
        return [line.strip() for line in self.features.splitlines() if line.strip()]
