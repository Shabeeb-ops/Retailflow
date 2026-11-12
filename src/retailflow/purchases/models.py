from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone


def money(value):
    """Round each line's discount and tax half-up to 2 decimals; sum rounded lines."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def amount_field(**kwargs):
    return models.DecimalField(max_digits=18, decimal_places=2, default=0,
                               validators=[MinValueValidator(0)], **kwargs)


class ValidatedModel(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        try:
            self.full_clean()
            return super().save(*args, **kwargs)
        finally:
            # Workflow permission lasts for one save, never for the returned object.
            self.__dict__.pop("_workflow", None)

    def delete(self, *args, **kwargs):
        raise ValidationError("Purchase history cannot be deleted.")


class PurchaseOrder(ValidatedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ORDERED = "ORDERED", "Ordered"
        PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED", "Partially received"
        RECEIVED = "RECEIVED", "Received"
        CANCELLED = "CANCELLED", "Cancelled"

    company = models.ForeignKey("company.Company", on_delete=models.PROTECT)
    supplier = models.ForeignKey("suppliers.Supplier", on_delete=models.PROTECT)
    number = models.CharField(max_length=40)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT)
    order_date = models.DateField(default=timezone.localdate)
    expected_delivery_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [models.UniqueConstraint(fields=["company", "number"], name="purchase_order_company_number")]

    def clean(self):
        if self.company_id and self.supplier_id and self.supplier.company_id != self.company_id:
            raise ValidationError({"supplier": "Supplier must belong to this company."})
        if self.expected_delivery_date and self.order_date and self.expected_delivery_date < self.order_date:
            raise ValidationError({"expected_delivery_date": "Delivery date cannot precede the order date."})
        if self.pk:
            old = PurchaseOrder.objects.get(pk=self.pk)
            if old.company_id != self.company_id or old.number != self.number or old.created_by_id != self.created_by_id:
                raise ValidationError("Order ownership, number and creator cannot change.")
            if not getattr(self, "_workflow", False) and (old.status != self.Status.DRAFT or self.status != old.status):
                raise ValidationError("Only draft orders can be edited. Use the order actions to change status.")
        elif self.status != self.Status.DRAFT:
            raise ValidationError("New orders must start as drafts.")

    @property
    def totals(self):
        lines = list(self.items.all())
        return {key: sum((getattr(line, key) for line in lines), Decimal("0.00"))
                for key in ("subtotal", "discount_amount", "tax_amount", "line_total")}

    def __str__(self):
        return self.number


class PurchaseOrderItem(ValidatedModel):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="items")
    product = models.ForeignKey("products.Product", on_delete=models.PROTECT)
    product_name = models.CharField(max_length=200, editable=False)
    product_sku = models.CharField(max_length=100, editable=False)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_cost = amount_field()
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    tax_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(fields=["order", "product"], name="purchase_order_unique_product"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0, unit_cost__gte=0, discount_percent__gte=0, discount_percent__lte=100, tax_percent__gte=0, tax_percent__lte=100), name="purchase_order_item_valid_amounts"),
        ]

    def clean(self):
        if self.order_id and self.product_id:
            if self.product.company_id != self.order.company_id:
                raise ValidationError({"product": "Product must belong to the order company."})
            if not PurchaseOrder.objects.filter(pk=self.order_id, status=PurchaseOrder.Status.DRAFT).exists():
                raise ValidationError("Items on placed orders cannot be edited.")
        if self.pk:
            old = PurchaseOrderItem.objects.get(pk=self.pk)
            if old.order_id != self.order_id:
                raise ValidationError("An order item cannot be moved to another order.")

    def save(self, *args, **kwargs):
        self.product_name, self.product_sku = self.product.name, self.product.sku
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if not PurchaseOrder.objects.filter(pk=self.order_id, status=PurchaseOrder.Status.DRAFT).exists():
            raise ValidationError("Only draft order items can be removed.")
        return models.Model.delete(self, *args, **kwargs)

    @property
    def subtotal(self):
        return money(self.quantity * self.unit_cost)

    @property
    def discount_amount(self):
        return money(self.subtotal * self.discount_percent / 100)

    @property
    def tax_amount(self):
        return money((self.subtotal - self.discount_amount) * self.tax_percent / 100)

    @property
    def line_total(self):
        return self.subtotal - self.discount_amount + self.tax_amount

    @property
    def received_quantity(self):
        return self.receipt_items.filter(receipt__status="CONFIRMED").aggregate(total=models.Sum("accepted_quantity"))["total"] or 0

    @property
    def remaining_quantity(self):
        return self.quantity - self.received_quantity

    def __str__(self):
        return f"{self.product_name} ({self.product_sku})"


class GoodsReceipt(ValidatedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        CONFIRMED = "CONFIRMED", "Confirmed"

    company = models.ForeignKey("company.Company", on_delete=models.PROTECT)
    order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="receipts")
    number = models.CharField(max_length=40)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    receipt_date = models.DateField(default=timezone.localdate)
    delivery_reference = models.CharField(max_length=100, blank=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="purchase_receipts")
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="confirmed_purchase_receipts", null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [models.UniqueConstraint(fields=["company", "number"], name="goods_receipt_company_number")]

    def clean(self):
        if self.company_id and self.order_id and self.order.company_id != self.company_id:
            raise ValidationError("Receipt and order must belong to the same company.")
        if self.pk:
            old = GoodsReceipt.objects.get(pk=self.pk)
            if old.company_id != self.company_id or old.order_id != self.order_id or old.number != self.number:
                raise ValidationError("Receipt ownership and references cannot change.")
            if old.status == self.Status.CONFIRMED:
                raise ValidationError("Confirmed receipts are immutable.")
        if self.status == self.Status.CONFIRMED and not getattr(self, "_workflow", False):
            raise ValidationError("Use the confirmation action to confirm a receipt.")

    def __str__(self):
        return self.number


class GoodsReceiptItem(ValidatedModel):
    receipt = models.ForeignKey(GoodsReceipt, on_delete=models.PROTECT, related_name="items")
    order_item = models.ForeignKey(PurchaseOrderItem, on_delete=models.PROTECT, related_name="receipt_items")
    accepted_quantity = models.PositiveIntegerField(default=0)
    damaged_quantity = models.PositiveIntegerField(default=0)
    rejected_quantity = models.PositiveIntegerField(default=0)
    notes = models.CharField(max_length=250, blank=True)

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(fields=["receipt", "order_item"], name="receipt_unique_order_item"),
            models.CheckConstraint(condition=models.Q(accepted_quantity__gt=0) | models.Q(damaged_quantity__gt=0) | models.Q(rejected_quantity__gt=0), name="receipt_item_nonempty"),
        ]

    def clean(self):
        if self.receipt_id and self.order_item_id:
            if self.receipt.order_id != self.order_item.order_id:
                raise ValidationError("Receipt item must reference this purchase order.")
            if self.order_item.product.company_id != self.receipt.company_id:
                raise ValidationError("Product must belong to the receipt company.")
            if not GoodsReceipt.objects.filter(pk=self.receipt_id, status=GoodsReceipt.Status.DRAFT).exists():
                raise ValidationError("Confirmed receipt quantities cannot change.")
        if self.pk:
            old = GoodsReceiptItem.objects.get(pk=self.pk)
            if old.receipt_id != self.receipt_id:
                raise ValidationError("Receipt items cannot be moved.")


class PurchaseInvoice(ValidatedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending verification"
        VERIFIED = "VERIFIED", "Verified against supplier bill"

    company = models.ForeignKey("company.Company", on_delete=models.PROTECT)
    supplier = models.ForeignKey("suppliers.Supplier", on_delete=models.PROTECT)
    order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="invoices")
    receipt = models.OneToOneField(GoodsReceipt, on_delete=models.PROTECT, related_name="invoice")
    number = models.CharField(max_length=40)
    supplier_invoice_number = models.CharField(max_length=100, blank=True)
    invoice_date = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    currency = models.CharField(max_length=10)
    company_snapshot = models.JSONField(default=dict)
    supplier_snapshot = models.JSONField(default=dict)
    subtotal = amount_field()
    discounts = amount_field()
    tax_amount = amount_field()
    additional_charges = amount_field()
    grand_total = amount_field()
    notes = models.TextField(blank=True)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["company", "number"], name="purchase_invoice_company_number"),
            models.CheckConstraint(condition=models.Q(subtotal__gte=0, discounts__gte=0, tax_amount__gte=0, additional_charges__gte=0, grand_total__gte=0), name="purchase_invoice_nonnegative"),
        ]

    def clean(self):
        if self.company_id and self.order_id and self.receipt_id and self.supplier_id:
            if self.order.company_id != self.company_id or self.supplier.company_id != self.company_id or self.receipt.company_id != self.company_id or self.receipt.order_id != self.order_id or self.order.supplier_id != self.supplier_id:
                raise ValidationError("Invoice references must belong to the same company and order.")
            if self.receipt.status != GoodsReceipt.Status.CONFIRMED:
                raise ValidationError("Invoices require a confirmed goods receipt.")
        if self.pk:
            old = PurchaseInvoice.objects.get(pk=self.pk)
            if old.status == self.Status.VERIFIED:
                raise ValidationError("Verified invoices are immutable.")
            for field in ("company_id", "supplier_id", "order_id", "receipt_id", "number", "currency", "company_snapshot", "supplier_snapshot", "subtotal", "discounts"):
                if getattr(old, field) != getattr(self, field):
                    raise ValidationError("Invoice history and source amounts cannot be changed.")
        if self.status == self.Status.VERIFIED and (not getattr(self, "_workflow", False) or not self.supplier_invoice_number or not self.verified_at):
            raise ValidationError("Verify the actual supplier bill through reconciliation.")

    @property
    def estimated_tax(self):
        return sum((line.tax_amount for line in self.items.all()), Decimal("0.00"))

    @property
    def paid_amount(self):
        return self.payments.aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")

    @property
    def outstanding(self):
        return self.grand_total - self.paid_amount

    @property
    def payment_status(self):
        paid = self.paid_amount
        if not paid:
            return "Unpaid"
        return "Paid" if paid == self.grand_total else "Partially paid"

    def __str__(self):
        return self.number


class PurchaseInvoiceItem(ValidatedModel):
    invoice = models.ForeignKey(PurchaseInvoice, on_delete=models.PROTECT, related_name="items")
    receipt_item = models.OneToOneField(GoodsReceiptItem, on_delete=models.PROTECT)
    product = models.ForeignKey("products.Product", on_delete=models.PROTECT)
    product_name = models.CharField(max_length=200)
    product_sku = models.CharField(max_length=100)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_cost = amount_field()
    subtotal = amount_field()
    discount_amount = amount_field()
    tax_amount = amount_field()
    line_total = amount_field()

    class Meta:
        ordering = ["pk"]
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gt=0, unit_cost__gte=0, subtotal__gte=0, discount_amount__gte=0, tax_amount__gte=0, line_total__gte=0), name="purchase_invoice_item_valid")]

    def clean(self):
        if self.pk:
            raise ValidationError("Invoice line snapshots cannot be edited.")
        if self.invoice_id and self.receipt_item_id and self.product_id:
            if self.receipt_item.receipt_id != self.invoice.receipt_id or self.product.company_id != self.invoice.company_id or self.receipt_item.order_item.product_id != self.product_id or self.quantity != self.receipt_item.accepted_quantity:
                raise ValidationError("Invoice line must match accepted goods from this receipt.")


class PurchasePayment(ValidatedModel):
    class Method(models.TextChoices):
        BANK = "BANK", "Bank transfer"
        CASH = "CASH", "Cash"
        CHEQUE = "CHEQUE", "Cheque"
        UPI = "UPI", "UPI"
        OTHER = "OTHER", "Other"

    invoice = models.ForeignKey(PurchaseInvoice, on_delete=models.PROTECT, related_name="payments")
    payment_date = models.DateField(default=timezone.localdate)
    amount = models.DecimalField(max_digits=18, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    method = models.CharField(max_length=10, choices=Method.choices)
    reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    request_key = models.UUIDField()
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["invoice", "request_key"], name="purchase_payment_request_unique"),
            models.UniqueConstraint(fields=["invoice", "reference"], condition=~models.Q(reference=""), name="purchase_payment_reference_unique"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="purchase_payment_positive"),
        ]

    def clean(self):
        if self.pk:
            raise ValidationError("Payment history cannot be edited.")
        if self.invoice_id:
            if self.invoice.status != PurchaseInvoice.Status.VERIFIED:
                raise ValidationError("Verify the supplier bill before recording payments.")
            if self.recorded_by_id and self.recorded_by_id != self.invoice.company.user_id:
                raise ValidationError("Payments must be recorded by the company owner.")
            if self.amount is not None and self.amount > self.invoice.outstanding:
                raise ValidationError({"amount": "Payment exceeds the outstanding balance."})
