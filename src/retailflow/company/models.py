import uuid
from django.db import models
from accounts.models import User

class Company(models.Model):
    COUNTRY_CHOICES = [
        ("IN","India"),
        ("US","United States"),
        ("UK","United Kingdom"),
        ("AE","United Arab Emirates"),
        ("SA","Saudi Arabia"),
        ("CA","Canada"),
    ]

    CURRENCY_CHOICES = [
        ("INR", "Indian Rupee (₹)"),
        ("USD", "US Dollar ($)"),
        ("GBP", "British Pound (£)"),
        ("AED", "UAE Dirham (د.إ)"),
        ("SAR", "Saudi Riyal (﷼)"),
        ("CAD", "Canadian Dollar ($)"),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="company"

    )
    company_name = models.CharField(max_length=100)

    address = models.TextField()

    company_registration_number = models.CharField(
        max_length=100,
        unique=True,

    )

    state = models.CharField(max_length=100)

    country = models.CharField(max_length=100,choices=COUNTRY_CHOICES)

    currency = models.CharField(max_length=100,choices=CURRENCY_CHOICES)

    phone = models.CharField(max_length=20)

    email = models.EmailField(max_length=50)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.company_name



class Branch(models.Model):

    class BranchType(models.TextChoices):
        RETAIL_STORE = "RETAIL_STORE", "Retail Store"
        WAREHOUSE = "WAREHOUSE", "Warehouse"
        OUTLET = "OUTLET", "Outlet"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="branches",
    )

    name = models.CharField(
        max_length=150,
    )

    code = models.CharField(
        max_length=30,
    )

    branch_type = models.CharField(
        max_length=20,
        choices=BranchType.choices,
        default=BranchType.RETAIL_STORE,
    )

    address = models.TextField(
        blank=True,
    )

    phone = models.CharField(
        max_length=20,
        blank=True,
    )

    email = models.EmailField(
        blank=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["name"]

        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"],
                name="unique_branch_code_per_company",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"
