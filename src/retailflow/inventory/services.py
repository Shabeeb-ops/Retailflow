
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Inventory, StockMovement


@transaction.atomic
def record_stock_movement(
    *,
    company,
    product,
    movement_type,
    quantity,
    reason="",
):
    # 1. Validate the quantity.
    if quantity <= 0:
        raise ValidationError(
            "Quantity must be greater than zero."
        )

    # 2. Ensure the product belongs to this company.
    if product.company_id != company.pk:
        raise ValidationError(
            "This product does not belong to your company."
        )

    # 3. Validate the movement type.
    allowed_types = StockMovement.MovementType.values

    if movement_type not in allowed_types:
        raise ValidationError("Invalid stock movement type.")

    # 4. Get or create the inventory record.
    inventory, created = Inventory.objects.get_or_create(
        company=company,
        product=product,
        defaults={
            "quantity": 0,
            "damaged_quantity": 0,
        },
    )

    # 5. Confirm that the inventory belongs to this company.
    if inventory.company_id != company.pk:
        raise ValidationError(
            "This inventory belongs to another company."
        )

    # 6. Lock the inventory row before changing its quantity.
    inventory = Inventory.objects.select_for_update().get(
        pk=inventory.pk
    )

    # 7. Calculate the new stock balance.
    if movement_type == StockMovement.MovementType.STOCK_IN:
        inventory.quantity += quantity

    elif movement_type == StockMovement.MovementType.STOCK_OUT:
        if inventory.quantity < quantity:
            raise ValidationError("Insufficient stock.")

        inventory.quantity -= quantity

    elif movement_type == StockMovement.MovementType.DAMAGE:
        if inventory.quantity < quantity:
            raise ValidationError(
                "Not enough stock to record this damage."
            )

        inventory.quantity -= quantity
        inventory.damaged_quantity += quantity

    elif movement_type == StockMovement.MovementType.ADJUSTMENT:
        raise ValidationError(
            "Stock adjustment is not implemented yet."
        )

    # 8. Save the new stock balance.
    inventory.save(
        update_fields=[
            "quantity",
            "damaged_quantity",
            "updated_at",
        ]
    )

    # 9. Save the movement history.
    StockMovement.objects.create(
        inventory=inventory,
        movement_type=movement_type,
        quantity=quantity,
        reason=reason,
    )

    # 10. Return the updated inventory object.
    return inventory
