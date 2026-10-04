from django.contrib import admin

from .models import AuditLog, DutyShift, LocationPing, TaxCollection, TaxType, Taxpayer


@admin.register(TaxType)
class TaxTypeAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "department", "default_amount", "currency", "frequency",
                    "max_collector_discount_percent", "is_active"]
    list_filter = ["department", "currency", "frequency", "is_active"]
    search_fields = ["code", "name"]


@admin.register(Taxpayer)
class TaxpayerAdmin(admin.ModelAdmin):
    list_display = ["taxpayer_number", "name", "business_name", "kind", "phone", "village",
                    "is_active"]
    list_filter = ["kind", "is_active", "village__district"]
    search_fields = ["taxpayer_number", "name", "business_name", "phone", "national_id",
                     "property_number"]
    readonly_fields = ["taxpayer_number", "created_at", "created_by"]
    autocomplete_fields = ["village"]


@admin.register(TaxCollection)
class TaxCollectionAdmin(admin.ModelAdmin):
    """Read-only: payments are corrected by voiding from the app, never edited."""

    list_display = ["receipt_number", "collected_at", "collector", "department", "tax_type",
                    "payer_name", "amount_paid", "currency", "payment_method", "status"]
    list_filter = ["status", "department", "payment_method", "currency", "tax_type",
                   "village__district"]
    search_fields = ["receipt_number", "payer_name", "payer_phone", "transaction_reference",
                     "collector__employee_id"]
    date_hierarchy = "collected_at"
    list_select_related = ["collector", "department", "tax_type"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "user", "action", "object_type", "object_id", "ip_address"]
    list_filter = ["action"]
    search_fields = ["object_id", "user__username"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(DutyShift)
class DutyShiftAdmin(ReadOnlyAdmin):
    list_display = ["collector", "started_at", "ended_at"]
    list_filter = ["collector__department"]
    date_hierarchy = "started_at"


@admin.register(LocationPing)
class LocationPingAdmin(ReadOnlyAdmin):
    list_display = ["collector", "recorded_at", "latitude", "longitude", "altitude", "accuracy",
                    "source"]
    list_filter = ["source", "collector__department"]
    date_hierarchy = "recorded_at"
