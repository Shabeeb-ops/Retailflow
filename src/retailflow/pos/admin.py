from django.contrib import admin
from .models import POSHeldCart, POSPayment, POSSale, POSSaleItem, POSSettings


class POSSaleItemInline(admin.TabularInline):
    model = POSSaleItem
    extra = 0
    readonly_fields = ("product", "product_name", "product_sku", "quantity", "unit_price", "discount_amount", "tax_amount", "line_total")


class POSPaymentInline(admin.TabularInline):
    model = POSPayment
    extra = 0
    readonly_fields = ("payment_method", "amount", "amount_tendered", "change_due", "reference", "status", "created_at")


@admin.register(POSSale)
class POSSaleAdmin(admin.ModelAdmin):
    list_display = ("sale_number", "company", "cashier", "grand_total", "status", "created_at")
    list_filter = ("status", "company", "created_at")
    search_fields = ("sale_number", "customer_name", "customer_phone", "idempotency_key")
    inlines = [POSSaleItemInline, POSPaymentInline]
    readonly_fields = ("sale_number", "idempotency_key", "created_at")


@admin.register(POSSettings)
class POSSettingsAdmin(admin.ModelAdmin):
    list_display = ("company", "display_mode", "paper_width", "enable_images", "show_stock")


@admin.register(POSHeldCart)
class POSHeldCartAdmin(admin.ModelAdmin):
    list_display = ("hold_reference", "company", "cashier", "customer_note", "created_at")
