
from django.contrib import admin

from .models import Inventory, StockMovement


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = (
        "company",
        "product",
        "quantity",
        "damaged_quantity",
        "updated_at",
    )

    list_filter = (
        "company",
    )

    search_fields = (
        "product__name",
        "product__sku",
    )



@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):

    list_display = (
        "company_name",
        "inventory",
        "movement_type",
        "quantity",
        "reason",
        "created_at",
    )

    list_filter = (
        "movement_type",
        "created_at",
    )

    search_fields = (
        "inventory__product__name",
        "inventory__product__sku",
        "inventory__company__company_name",
    )

    list_select_related = (
        "inventory__company",
        "inventory__product",
    )

    @admin.display(
        description="Company (Tenant)",
        ordering="inventory__company__company_name",
    )
    def company_name(self, obj):
        return obj.inventory.company.company_name

