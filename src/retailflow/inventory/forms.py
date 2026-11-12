
from django import forms

from products.models import Product
from .models import StockMovement


class StockMovementForm(forms.Form):

    product = forms.ModelChoiceField(
        queryset=Product.objects.none(),
        empty_label="Select a product",
    )

    movement_type = forms.ChoiceField(
        choices=[
            (
                StockMovement.MovementType.STOCK_IN,
                "Stock In",
            ),
            (
                StockMovement.MovementType.STOCK_OUT,
                "Stock Out",
            ),
            (
                StockMovement.MovementType.DAMAGE,
                "Damaged Stock",
            ),
        ]
    )

    quantity = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(
            attrs={"placeholder": "Enter quantity", "min": 1}
        ),
    )

    reason = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={"placeholder": "Enter reason"}
        ),
    )

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)

        if company is not None:
            self.fields["product"].queryset = Product.objects.filter(
                company=company,
                is_active=True,
            )
