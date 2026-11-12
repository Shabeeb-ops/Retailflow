from django.core.exceptions import ValidationError
from django.db.models import Q
from django.db import models
from django.core.validators import MinValueValidator

from company.models import Company


class Supplier(models.Model):

    # ===== COMPANY OWNERSHIP =====

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="suppliers",
    )

    # ===== SUPPLIER INFORMATION =====

    supplier_code = models.CharField(
        max_length=30,
    )

    name = models.CharField(
        max_length=150,
    )

    contact_person = models.CharField(
        max_length=100,
        blank=True,
    )

    # ===== CONTACT INFORMATION =====

    phone = models.CharField(
        max_length=20,
        blank=True,
    )

    alternate_phone = models.CharField(
        max_length=20,
        blank=True,
    )

    email = models.EmailField(
        blank=True,
    )

    # ===== ADDRESS =====

    address = models.TextField(
        blank=True,
    )

    city = models.CharField(
        max_length=100,
        blank=True,
    )

    state = models.CharField(
        max_length=100,
        blank=True,
    )

    postal_code = models.CharField(
        max_length=15,
        blank=True,
    )

    # ===== BUSINESS DETAILS =====

    gstin = models.CharField(
        max_length=15,
        blank=True,
    )

    payment_terms_days = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
    )

    # ===== WHATSAPP SETTINGS =====

    whatsapp_number = models.CharField(
        max_length=20,
        blank=True,
        help_text="Include country code, e.g. +919876543210",
    )

    whatsapp_opt_in = models.BooleanField(
        default=False,
        help_text="Supplier has agreed to receive WhatsApp notifications.",
    )

    whatsapp_opt_in_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Date and time supplier consent was recorded.",
    )

    auto_stock_alerts_enabled = models.BooleanField(
        default=False,
        help_text="Allow automatic low-stock messages to this supplier.",
    )

    # ===== STATUS =====

    is_active = models.BooleanField(
        default=True,
    )

    notes = models.TextField(
        blank=True,
    )

    # ===== TIMESTAMPS =====

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    # ===== DATABASE RULES =====

    class Meta:
        ordering = ["name", "pk"]

        constraints = [
            models.UniqueConstraint(
                fields=["company", "supplier_code"],
                name="unique_supplier_code_per_company",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.supplier_code})"


class SupplierProduct(models.Model):

    company = models.ForeignKey(
        "company.Company",
        on_delete=models.CASCADE,
        related_name="supplier_products",
    )

    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.CASCADE,
        related_name="supplied_products",
    )

    product = models.ForeignKey(
        "products.Product",
        on_delete=models.CASCADE,
        related_name="supplier_links",
    )

    is_preferred = models.BooleanField(
        default=False,
        help_text="Preferred supplier for this product.",
    )

    is_active = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "supplier", "product"],
                name="unique_supplier_product_per_company",
            ),
            models.UniqueConstraint(
                fields=["company", "product"],
                condition=Q(is_preferred=True),
                name="one_preferred_supplier_per_product",
            ),
        ]

    def clean(self):
        super().clean()

        if self.company_id and self.supplier_id:
            if self.supplier.company_id != self.company_id:
                raise ValidationError(
                    "Supplier must belong to the selected company."
                )

        if self.company_id and self.product_id:
            if self.product.company_id != self.company_id:
                raise ValidationError(
                    "Product must belong to the selected company."
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product} - {self.supplier}"
