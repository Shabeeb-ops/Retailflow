import uuid

from django import forms
from django.forms import formset_factory

from products.models import Product
from suppliers.models import Supplier
from .models import PurchaseOrder, PurchaseOrderItem, GoodsReceipt, PurchaseInvoice, PurchasePayment


class PurchaseOrderForm(forms.ModelForm):
    class Meta:
        model = PurchaseOrder
        fields = ["supplier", "order_date", "expected_delivery_date", "notes"]
        widgets = {"order_date": forms.DateInput(attrs={"type": "date"}),
                   "expected_delivery_date": forms.DateInput(attrs={"type": "date"}),
                   "notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.company = company
        self.fields["supplier"].queryset = Supplier.objects.filter(company=company, is_active=True)


class PurchaseOrderItemForm(forms.ModelForm):
    class Meta:
        model = PurchaseOrderItem
        fields = ["product", "quantity", "unit_cost", "discount_percent", "tax_percent"]

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.filter(company=company, is_active=True).order_by("name", "pk")


class OrderItemsFormSet(forms.BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        products = [form.cleaned_data["product"].pk for form in self.forms if form.cleaned_data and not form.cleaned_data.get("DELETE")]
        if not products:
            raise forms.ValidationError("Add at least one product.")
        if len(products) != len(set(products)):
            raise forms.ValidationError("Each product can appear only once.")


OrderItemFormSet = formset_factory(PurchaseOrderItemForm, formset=OrderItemsFormSet, extra=1, can_delete=True, max_num=200, validate_max=True)


class GoodsReceiptForm(forms.ModelForm):
    class Meta:
        model = GoodsReceipt
        fields = ["receipt_date", "delivery_reference", "notes"]
        widgets = {"receipt_date": forms.DateInput(attrs={"type": "date"}), "notes": forms.Textarea(attrs={"rows": 3})}


class GoodsReceiptItemForm(forms.Form):
    # Zero rows are permitted in the delivery worksheet and omitted on save.
    order_item = forms.ModelChoiceField(queryset=PurchaseOrderItem.objects.none())
    accepted_quantity = forms.IntegerField(min_value=0, initial=0)
    damaged_quantity = forms.IntegerField(min_value=0, initial=0)
    rejected_quantity = forms.IntegerField(min_value=0, initial=0)
    notes = forms.CharField(max_length=250, required=False)

    def __init__(self, *args, order, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["order_item"].queryset = order.items.filter(product__company=order.company)
        self.fields["order_item"].label_from_instance = lambda item: f"{item} — ordered {item.quantity}, accepted {item.received_quantity}, remaining {item.remaining_quantity}"


ReceiptItemFormSet = formset_factory(GoodsReceiptItemForm, extra=0, max_num=200, validate_max=True)


class InvoiceReconciliationForm(forms.ModelForm):
    verified = forms.BooleanField(label="I verified these allocated amounts against the supplier's actual bill.")

    class Meta:
        model = PurchaseInvoice
        fields = ["supplier_invoice_number", "invoice_date", "tax_amount", "additional_charges", "notes"]
        widgets = {"invoice_date": forms.DateInput(attrs={"type": "date"}), "notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier_invoice_number"].required = True


class PurchasePaymentForm(forms.ModelForm):
    request_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)

    class Meta:
        model = PurchasePayment
        fields = ["payment_date", "amount", "method", "reference", "notes", "request_key"]
        widgets = {"payment_date": forms.DateInput(attrs={"type": "date"}), "notes": forms.Textarea(attrs={"rows": 3})}
