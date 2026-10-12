from django.contrib import admin

from tenants.models import Tenant, TenantMembership, TenantSettings


class TenantMembershipInline(admin.TabularInline):
    model = TenantMembership
    extra = 0


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    inlines = (TenantMembershipInline,)


@admin.register(TenantSettings)
class TenantSettingsAdmin(admin.ModelAdmin):
    list_display = ("tenant", "display_name", "timezone", "updated_at")
    search_fields = ("tenant__name", "tenant__slug", "display_name")
