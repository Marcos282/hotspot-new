from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models


RESERVED_SLUGS = {
    "admin",
    "api",
    "gestao",
    "mail",
    "static",
    "www",
}


def validate_tenant_slug(value):
    if value.lower() in RESERVED_SLUGS:
        raise ValidationError("Este subdomínio está reservado.")


tenant_slug_validator = RegexValidator(
    regex=r"(?i)^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$",
    message="Use letras minúsculas, números e hífens em um subdomínio válido.",
)


class Tenant(models.Model):
    name = models.CharField("nome fantasia / estabelecimento", max_length=150)
    legal_name = models.CharField(
        "razão social", max_length=200, blank=True, help_text="Razão social jurídica ou nome completo do responsável."
    )
    document_number = models.CharField(
        "CNPJ / CPF", max_length=20, blank=True, help_text="CNPJ ou CPF do titular do estabelecimento."
    )
    email = models.EmailField(
        "e-mail de contato", blank=True, help_text="E-mail principal para contato e notificações."
    )
    phone = models.CharField(
        "telefone / WhatsApp", max_length=32, blank=True, help_text="Telefone ou WhatsApp de contato comercial/técnico."
    )
    responsible_name = models.CharField(
        "nome do responsável", max_length=120, blank=True, help_text="Nome do titular ou contato responsável."
    )
    address = models.CharField("endereço completo", max_length=255, blank=True)
    city = models.CharField("cidade", max_length=100, blank=True)
    state = models.CharField("UF", max_length=2, blank=True)
    postal_code = models.CharField("CEP", max_length=10, blank=True)
    notes = models.TextField("observações internas", blank=True)
    slug = models.CharField(
        "subdomínio",
        max_length=63,
        unique=True,
        validators=[tenant_slug_validator, validate_tenant_slug],
    )
    is_active = models.BooleanField("ativo", default=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["is_active", "slug"])]
        verbose_name = "estabelecimento"
        verbose_name_plural = "estabelecimentos"

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        self.slug = self.slug.lower()

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class TenantMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Proprietário"
        ADMIN = "admin", "Administrador"
        STAFF = "staff", "Equipe"
        VIEWER = "viewer", "Somente leitura"

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tenant_memberships"
    )
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.VIEWER)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "user"], name="unique_tenant_user_membership"
            )
        ]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["tenant", "is_active"]),
        ]
        verbose_name = "associação de usuário"
        verbose_name_plural = "associações de usuários"

    def __str__(self):
        return f"{self.user} — {self.tenant} ({self.get_role_display()})"


class TenantScopedQuerySet(models.QuerySet):
    def for_tenant(self, tenant):
        if tenant is None or not getattr(tenant, "pk", None):
            raise ValueError("Uma instância de tenant persistida é obrigatória.")
        return self.filter(tenant=tenant)


class TenantScopedManager(models.Manager.from_queryset(TenantScopedQuerySet)):
    pass


class TenantOwnedModel(models.Model):
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_records",
    )
    objects = TenantScopedManager()

    class Meta:
        abstract = True


class TenantSettings(TenantOwnedModel):
    tenant = models.OneToOneField(
        Tenant, on_delete=models.CASCADE, related_name="settings"
    )
    display_name = models.CharField("nome de exibição", max_length=150, blank=True)
    timezone = models.CharField("fuso horário", max_length=64, default="America/Sao_Paulo")
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "configuração do estabelecimento"
        verbose_name_plural = "configurações dos estabelecimentos"

    def __str__(self):
        return self.display_name or self.tenant.name
