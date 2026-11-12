import re

from django import forms
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from company.context import get_current_tenant
from products.models import Product
from .models import Supplier, SupplierProduct


class TenantForm(forms.ModelForm):
    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company or get_current_tenant()
        if self.company is None:
            raise PermissionDenied("No company is associated with this account.")
        if self.instance.pk and self.instance.company_id != self.company.pk:
            raise PermissionDenied("This record belongs to another company.")
        self.instance.company = self.company


class SupplierForm(TenantForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.had_consent = self.instance.whatsapp_opt_in

    class Meta:
        model = Supplier
        fields = [
            "supplier_code", "name", "contact_person", "phone", "alternate_phone",
            "email", "address", "city", "state", "postal_code", "gstin",
            "payment_terms_days", "whatsapp_number", "whatsapp_opt_in",
            "auto_stock_alerts_enabled", "is_active", "notes",
        ]
        widgets = {"address": forms.Textarea(attrs={"rows": 3}),
                   "notes": forms.Textarea(attrs={"rows": 3})}

    def clean_supplier_code(self):
        code = self.cleaned_data["supplier_code"].upper()
        if Supplier.objects.filter(company=self.company, supplier_code__iexact=code).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("This supplier code already exists in your company.")
        return code

    def clean_gstin(self):
        gstin = self.cleaned_data["gstin"].upper()
        if gstin and not re.fullmatch(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]", gstin):
            raise forms.ValidationError("Enter a valid 15-character GSTIN.")
        return gstin

    def clean_whatsapp_number(self):
        number = self.cleaned_data["whatsapp_number"]
        if number and not re.fullmatch(r"\+[1-9][0-9]{7,14}", number):
            raise forms.ValidationError("Enter a valid WhatsApp number including + and country code.")
        return number

    def clean(self):
        data = super().clean()
        if data.get("whatsapp_opt_in") and not data.get("whatsapp_number"):
            self.add_error("whatsapp_number", "A valid WhatsApp number is required for consent.")
        if not data.get("whatsapp_opt_in"):
            if self.had_consent:
                data["auto_stock_alerts_enabled"] = False
            elif data.get("auto_stock_alerts_enabled"):
                self.add_error("auto_stock_alerts_enabled", "Supplier consent is required for automatic alerts.")
        return data

    def save(self, commit=True):
        supplier = super().save(commit=False)
        if supplier.whatsapp_opt_in:
            if not self.had_consent or supplier.whatsapp_opt_in_at is None:
                supplier.whatsapp_opt_in_at = timezone.now()
        else:
            supplier.whatsapp_opt_in_at = None
            supplier.auto_stock_alerts_enabled = False
        if commit:
            supplier.save()
        return supplier


class SupplierProductForm(TenantForm):
    class Meta:
        model = SupplierProduct
        fields = ["supplier", "product", "is_preferred", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Supplier.objects.filter(company=self.company)
        self.fields["product"].queryset = Product.objects.filter(company=self.company).order_by("name", "pk")

    def clean(self):
        data = super().clean()
        supplier, product = data.get("supplier"), data.get("product")
        links = SupplierProduct.objects.filter(company=self.company).exclude(pk=self.instance.pk)
        if supplier and product and links.filter(supplier=supplier, product=product).exists():
            self.add_error(None, "This supplier-product relationship already exists. Edit the existing relationship instead.")
        if product and data.get("is_preferred") and links.filter(product=product, is_preferred=True).exists():
            self.add_error("is_preferred", "This product already has a preferred supplier. Clear that preference first.")
        if data.get("is_preferred") and not data.get("is_active"):
            self.add_error("is_preferred", "An inactive relationship cannot be preferred.")
        return data
