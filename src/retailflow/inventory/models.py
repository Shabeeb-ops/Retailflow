
from django.db import models
from company.models import Company
from products.models import Product



class Inventory(models.Model):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="inventory",
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="inventory_records",
    )

    quantity = models.PositiveIntegerField(default=0)

    damaged_quantity = models.PositiveIntegerField(default=0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "inventory_inventory"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "product"],
                name="unique_inventory_company_product",
            )
        ]

    def __str__(self):
        return f"{self.product.name} - {self.quantity}"



class StockMovement(models.Model):
    class MovementType(models.TextChoices):
        STOCK_IN = "IN", "Stock In"
        STOCK_OUT = "OUT", "Stock Out"
        DAMAGE = "DAMAGE", "Damaged"
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"


    inventory = models.ForeignKey(
        Inventory,
        on_delete=models.CASCADE,
        related_name = "movements"
    )

    movement_type = models.CharField(max_length=10,choices=MovementType.choices,)

    quantity = models.PositiveIntegerField()

    reason = models.CharField(max_length=100,blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inventory_stock_movement"
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"{self.inventory.product.name} - "
            f"{self.movement_type} - {self.quantity}"
        )