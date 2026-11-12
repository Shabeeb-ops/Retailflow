from django.contrib import admin

from .models import PurchaseOrder, PurchaseOrderItem, GoodsReceipt, GoodsReceiptItem, PurchaseInvoice, PurchaseInvoiceItem, PurchasePayment


class PurchaseHistoryAdmin(admin.ModelAdmin):
    """Inspection only: workflow actions belong in the tenant-aware application."""
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser


for model in (PurchaseOrder, PurchaseOrderItem, GoodsReceipt, GoodsReceiptItem, PurchaseInvoice, PurchaseInvoiceItem, PurchasePayment):
    admin.site.register(model, PurchaseHistoryAdmin)
