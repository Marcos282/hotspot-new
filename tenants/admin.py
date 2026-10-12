from django.contrib import admin

from tenants.models import Tenant, TenantMembership, TenantSettings


class TenantMembershipInline(admin.TabularInline):
    model = TenantMembership
    extra = 0


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "slug",
        "responsible_name",
        "phone",
        "email",
        "is_active",
        "created_at",
    )
    list_filter = ("is_active", "state", "created_at")
    search_fields = (
        "name",
        "legal_name",
        "slug",
        "document_number",
        "responsible_name",
        "email",
        "phone",
    )
    fieldsets = (
        (
            "Identificação do Estabelecimento",
            {
                "fields": (
                    "name",
                    "legal_name",
                    "document_number",
                    "slug",
                    "is_active",
                )
            },
        ),
        (
            "Contato e Responsável",
            {
                "fields": (
                    "responsible_name",
                    "email",
                    "phone",
                )
            },
        ),
        (
            "Endereço e Localização",
            {
                "fields": (
                    "address",
                    "city",
                    "state",
                    "postal_code",
                )
            },
        ),
        (
            "Notas e Informações Internas",
            {
                "fields": ("notes",),
            },
        ),
    )
    inlines = (TenantMembershipInline,)


@admin.register(TenantSettings)
class TenantSettingsAdmin(admin.ModelAdmin):
    list_display = ("tenant", "display_name", "timezone", "updated_at")
    search_fields = ("tenant__name", "tenant__slug", "display_name")
