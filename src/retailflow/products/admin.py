
from django.contrib import admin
from .models import Product, Category


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "sku",
        "company",  # Shows the tenant
        "category",
        "purchase_price",
        "selling_price",
        "is_active",
    )

    list_filter = (
        "company",
        "category",
        "is_active",
    )

    search_fields = (
        "name",
        "sku",
        "company__company_name",
    )


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "company",  # Shows the tenant
        "is_active",
    )
