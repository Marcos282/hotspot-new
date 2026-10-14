from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator, MinValueValidator
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
    wireguard_ip = models.GenericIPAddressField(
        "IP WireGuard",
        protocol="IPv4",
        null=True,
        blank=True,
        help_text="Endereço IP atribuído ao roteador do cliente na VPN (ex: 10.10.0.2).",
    )
    wireguard_public_key = models.CharField(
        "Chave Pública WireGuard",
        max_length=64,
        blank=True,
        help_text="Chave pública do peer WireGuard no roteador MikroTik.",
    )
    wireguard_enabled = models.BooleanField(
        "WireGuard ativado",
        default=False,
        help_text="Marque se este estabelecimento possui túnel WireGuard configurado e ativo.",
    )
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


class Device(TenantOwnedModel):
    name = models.CharField("nome", max_length=120)
    management_ip = models.GenericIPAddressField("IP de gerência privado")
    routeros_version = models.CharField("versão RouterOS", max_length=32, blank=True)
    enabled = models.BooleanField("habilitado", default=True)
    last_seen = models.DateTimeField("última comunicação", null=True, blank=True)
    api_username = models.CharField("usuário API somente leitura", max_length=80, blank=True)
    api_password_encrypted = models.TextField(blank=True, editable=False)
    certificate_sha256 = models.CharField("SHA-256 do certificado API-SSL", max_length=64, blank=True)
    monitoring_enabled = models.BooleanField("monitoramento autorizado", default=False)
    session_collection_enabled = models.BooleanField("coleta de sessões autorizada", default=False, help_text="Ative apenas após definir finalidade, base legal e retenção.")
    privacy_purpose = models.CharField("finalidade/base legal documentada", max_length=500, blank=True)

    def __str__(self):
        return self.name


class AccessPlan(TenantOwnedModel):
    name = models.CharField("nome", max_length=100)
    duration_minutes = models.PositiveIntegerField("duração em minutos", validators=[MinValueValidator(1)])
    price = models.DecimalField("preço (R$)", max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    speed_limit = models.CharField("limite de velocidade", max_length=32, blank=True, help_text="Exemplo: 5M/10M. A aplicação ao roteador depende da integração.")
    enabled = models.BooleanField("ativo", default=True)

    def __str__(self):
        return self.name


class Sale(TenantOwnedModel):
    cash_request_id = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    duration_minutes = models.PositiveIntegerField("duração vendida (minutos)", null=True, blank=True)
    plan = models.ForeignKey(AccessPlan, on_delete=models.PROTECT)
    reference = models.CharField("referência", max_length=120)
    amount = models.DecimalField("valor", max_digits=10, decimal_places=2)
    status = models.CharField("situação", max_length=16, choices=[('pending', 'Pendente'), ('paid', 'Pago'), ('cancelled', 'Cancelado')], default='pending')
    created_at = models.DateTimeField(auto_now_add=True)


class Payment(TenantOwnedModel):
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['tenant','provider_reference'], name='unique_tenant_payment_reference'),
            models.UniqueConstraint(fields=['sale'], condition=models.Q(method='cash'), name='one_cash_payment_per_sale'),
            models.CheckConstraint(condition=~models.Q(method='cash') | (models.Q(received_by__isnull=False) & models.Q(received_at__isnull=False) & models.Q(amount__gt=0) & models.Q(status='paid')), name='cash_payment_requires_receipt'),
        ]

    method = models.CharField("forma de recebimento", max_length=16, choices=[('cash','Dinheiro'),('legacy','Não informado (registro anterior)')], default='legacy')
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='cash_receipts')
    received_at = models.DateTimeField("recebido em", null=True, blank=True)
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT)
    provider_reference = models.CharField(max_length=150)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)


class AccessSession(TenantOwnedModel):
    router_session_id = models.CharField(max_length=120, blank=True, db_index=True)
    device = models.ForeignKey(Device, on_delete=models.PROTECT)
    username = models.CharField(max_length=120)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    bytes_used = models.PositiveBigIntegerField(default=0)


class HotspotConfiguration(TenantOwnedModel):
    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name='hotspot')
    title = models.CharField("título do portal", max_length=120, default='Bem-vindo ao nosso Wi-Fi')
    welcome_text = models.TextField("mensagem de boas-vindas", blank=True, max_length=2000)
    free_access = models.BooleanField("oferecer acesso gratuito", default=False)
    updated_at = models.DateTimeField(auto_now=True)


class BrandImage(TenantOwnedModel):
    kind = models.CharField("tipo", max_length=16, choices=[('logo', 'Logotipo'), ('advertisement', 'Publicidade')])
    title = models.CharField("descrição", max_length=120)
    data = models.BinaryField()
    created_at = models.DateTimeField(auto_now_add=True)


class AuditEvent(TenantOwnedModel):
    fields_changed = models.JSONField(default=list, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=80)
    object_type = models.CharField(max_length=80)
    object_id = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)



class TenantRegistration(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tenant_registration')
    name = models.CharField('estabelecimento', max_length=150)
    responsible_name = models.CharField('nome do responsável', max_length=120, blank=True)
    phone = models.CharField('telefone / WhatsApp', max_length=32, blank=True)
    city = models.CharField('cidade', max_length=100, blank=True)
    slug = models.CharField('subdomínio desejado', max_length=63, unique=True, validators=[tenant_slug_validator, validate_tenant_slug])
    tenant = models.OneToOneField(Tenant, null=True, blank=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
