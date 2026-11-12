from django import forms
from .models import Category, Product


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "description", "is_active"]


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "name",
            "sku",
            "barcode",
            "category",
            "brand",
            "purchase_price",
            "selling_price",
            "unit",
            "low_stock_threshold",
            "description",
            "image",
            "is_active",
        ]

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)

        # Only show categories belonging to this company.
        if company is not None:
            self.fields["category"].queryset = Category.objects.filter(
                company=company,
                is_active=True,
            )