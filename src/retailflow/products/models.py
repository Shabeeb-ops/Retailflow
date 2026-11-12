from django.db import models
from company.models import Company

class Category(models.Model):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name ="categories"

    )

    name =models.CharField(max_length=100)
    description = models.CharField(max_length=100,blank=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateField(auto_now_add=True)
    class Meta:
        db_table = "products_category"
        ordering = ["name"]
        constraints = [models.UniqueConstraint(
            fields=["company","name"],
            name = "unique_category_per_company"
        )]



    def __str__(self):
        return self.name

class Product(models.Model):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="products"
    )
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=100)
    barcode = models.CharField(max_length=100, blank=True, db_index=True)
    image = models.FileField(upload_to="products/", blank=True, null=True)
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products"
    )
    brand = models.CharField(max_length=100,blank=True)
    purchase_price = models.DecimalField(max_digits=12,decimal_places=2)
    selling_price = models.DecimalField(max_digits=12,decimal_places=2)
    unit = models.CharField(max_length=30,default="Piece")
    low_stock_threshold = models.PositiveIntegerField(default=10)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "products_product"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "sku"],
                name="unique_product_sku_per_company"
            )
        ]

        # def __str__(self):
        #     return f"{self.name} ({self.sku})"



    def __str__(self):
        return self.name