from django.contrib import admin
from django.utils.html import format_html

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
        "wireguard_status_badge",
        "is_active",
        "created_at",
    )
    list_filter = ("wireguard_enabled", "is_active", "state", "created_at")
    search_fields = (
        "name",
        "legal_name",
        "slug",
        "document_number",
        "responsible_name",
        "email",
        "phone",
        "wireguard_ip",
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
            "Conectividade WireGuard (VPN)",
            {
                "fields": (
                    "wireguard_enabled",
                    "wireguard_ip",
                    "wireguard_public_key",
                ),
                "description": "Configurações de túnel seguro WireGuard para gerência remota do MikroTik.",
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

    @admin.display(description="WireGuard", ordering="wireguard_enabled")
    def wireguard_status_badge(self, obj):
        if obj.wireguard_enabled:
            label = obj.wireguard_ip or "Ativo"
            return format_html(
                '<span style="'
                'display: inline-flex; align-items: center; gap: 6px; '
                'padding: 3px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; '
                'background-color: #d1fae5; color: #065f46; border: 1px solid #a7f3d0;">'
                '<span style="width: 8px; height: 8px; border-radius: 50%; background-color: #10b981; display: inline-block;"></span>'
                'WG Ativo ({})'
                '</span>',
                label,
            )
        return format_html(
            '<span style="'
            'display: inline-flex; align-items: center; gap: 6px; '
            'padding: 3px 8px; border-radius: 12px; font-size: 11px; font-weight: 500; '
            'background-color: #f3f4f6; color: #6b7280; border: 1px solid #e5e7eb;">'
            '<span style="width: 8px; height: 8px; border-radius: 50%; background-color: #9ca3af; display: inline-block;"></span>'
            'Inativo'
            '</span>'
        )


@admin.register(TenantSettings)
class TenantSettingsAdmin(admin.ModelAdmin):
    list_display = ("tenant", "display_name", "timezone", "updated_at")
    search_fields = ("tenant__name", "tenant__slug", "display_name")
