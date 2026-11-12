from django import forms
from .models import POSSettings


class POSSettingsForm(forms.ModelForm):
    class Meta:
        model = POSSettings
        fields = [
            "display_mode",
            "paper_width",
            "enable_images",
            "show_stock",
            "enable_barcode",
            "enable_cash",
            "enable_upi",
            "enable_card",
            "enable_discount",
            "max_discount_percent",
            "receipt_header",
            "receipt_footer",
        ]
        widgets = {
            "display_mode": forms.Select(attrs={"class": "form-control"}),
            "paper_width": forms.Select(attrs={"class": "form-control"}),
            "max_discount_percent": forms.NumberInput(attrs={"class": "form-control", "step": "0.5", "min": "0", "max": "100"}),
            "receipt_header": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Store address, phone, GSTIN or greeting..."}),
            "receipt_footer": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Return policy or closing note..."}),
        }

