from django.db import models
from django.utils.translation import gettext_lazy as _
from company.models import Company


class POSSettings(models.Model):
    class DisplayMode(models.TextChoices):
        GRID = "GRID", _("Grid View")
        LIST = "LIST", _("Compact List View")

    class PaperWidth(models.TextChoices):
        WIDTH_58MM = "58mm", _("58mm (Small Thermal)")
        WIDTH_80MM = "80mm", _("80mm (Standard Thermal)")

    company = models.OneToOneField(
        Company,
        on_delete=models.CASCADE,
        related_name="pos_settings",
    )
    enable_images = models.BooleanField(default=True, help_text=_("Display product images in the catalog."))
    display_mode = models.CharField(
        max_length=10,
        choices=DisplayMode.choices,
        default=DisplayMode.GRID,
    )
    show_stock = models.BooleanField(default=True, help_text=_("Display stock badges on product cards."))
    enable_barcode = models.BooleanField(default=True, help_text=_("Enable barcode scan and instant search."))
    enable_cash = models.BooleanField(default=True, help_text=_("Accept cash payments at checkout."))
    enable_upi = models.BooleanField(default=True, help_text=_("Accept UPI payments at checkout."))
    enable_card = models.BooleanField(default=True, help_text=_("Accept card payments at checkout."))
    enable_discount = models.BooleanField(default=True, help_text=_("Allow cashier manual discount entry."))
    max_discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=20.00,
        help_text=_("Maximum discount percentage allowed at POS."),
    )
    receipt_header = models.TextField(
        blank=True,
        default="",
        help_text=_("Custom header note printed at the top of receipts."),
    )
    receipt_footer = models.TextField(
        blank=True,
        default="Thank you for shopping with us! Please visit again.",
        help_text=_("Custom footer note printed at the bottom of receipts."),
    )
    paper_width = models.CharField(
        max_length=10,
        choices=PaperWidth.choices,
        default=PaperWidth.WIDTH_80MM,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pos_settings"
        verbose_name = _("POS Settings")
        verbose_name_plural = _("POS Settings")

    def __str__(self):
        return f"POS Settings - {self.company}"


class POSSale(models.Model):
    class Status(models.TextChoices):
        COMPLETED = "COMPLETED", _("Completed")
        CANCELLED = "CANCELLED", _("Cancelled")

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="pos_sales",
    )
    cashier = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pos_sales",
    )
    sale_number = models.CharField(max_length=50, db_index=True)
    customer_name = models.CharField(max_length=150, blank=True)
    customer_phone = models.CharField(max_length=30, blank=True)

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    grand_total = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.COMPLETED,
        db_index=True,
    )
    idempotency_key = models.CharField(max_length=100, db_index=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "pos_sale"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "sale_number"],
                name="unique_pos_sale_number_per_company",
            )
        ]

    def __str__(self):
        return f"{self.sale_number} - {self.company}"


class POSSaleItem(models.Model):
    sale = models.ForeignKey(
        POSSale,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pos_sale_items",
    )
    product_name = models.CharField(max_length=200)
    product_sku = models.CharField(max_length=100)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        db_table = "pos_sale_item"

    def __str__(self):
        return f"{self.product_name} x {self.quantity} ({self.sale.sale_number})"


class POSPayment(models.Model):
    class Method(models.TextChoices):
        CASH = "CASH", _("Cash")
        UPI = "UPI", _("UPI")
        CARD = "CARD", _("Card")

    class Status(models.TextChoices):
        CONFIRMED = "CONFIRMED", _("Confirmed")
        REFUNDED = "REFUNDED", _("Refunded")

    sale = models.ForeignKey(
        POSSale,
        on_delete=models.CASCADE,
        related_name="payments",
    )
    payment_method = models.CharField(
        max_length=10,
        choices=Method.choices,
        default=Method.CASH,
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    amount_tendered = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    change_due = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    reference = models.CharField(max_length=100, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CONFIRMED,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pos_payment"

    def __str__(self):
        return f"{self.payment_method} - ₹{self.amount} for {self.sale.sale_number}"


class POSHeldCart(models.Model):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="held_carts",
    )
    cashier = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="held_carts",
    )
    hold_reference = models.CharField(max_length=100)
    customer_note = models.CharField(max_length=200, blank=True)
    cart_data = models.JSONField(help_text=_("JSON array of held cart items."))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pos_held_cart"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Held Cart {self.hold_reference} ({self.company})"
