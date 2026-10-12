from django.contrib import admin

from website.models import LeadRequest


@admin.register(LeadRequest)
class LeadRequestAdmin(admin.ModelAdmin):
    list_display = ("business_name", "name", "email", "phone", "created_at")
    list_filter = ("created_at",)
    search_fields = ("business_name", "name", "email", "phone")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)
