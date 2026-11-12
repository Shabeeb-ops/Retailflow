import datetime
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from company.models import Company
from inventory.models import StockMovement
from inventory.services import record_stock_movement
from products.models import Product
from .models import POSHeldCart, POSPayment, POSSale, POSSaleItem, POSSettings


def get_pos_settings(company: Company) -> POSSettings:
    """Retrieve or create default POSSettings for a company."""
    settings, _ = POSSettings.objects.get_or_create(company=company)
    return settings


def generate_sale_number(company: Company) -> str:
    """
    Generate sequential, unique sale numbers scoped to company and date.
    Format: POS-YYYYMMDD-0001
    """
    today_str = timezone.now().strftime("%Y%m%d")
    prefix = f"POS-{today_str}-"

    # Lock recent sales for this company to safely increment sequential number
    last_sale = (
        POSSale.objects.select_for_update()
        .filter(company=company, sale_number__startswith=prefix)
        .order_by("-sale_number")
        .first()
    )

    if last_sale:
        try:
            last_seq = int(last_sale.sale_number.split("-")[-1])
            new_seq = last_seq + 1
        except (ValueError, IndexError):
            new_seq = 1
    else:
        new_seq = 1

    return f"{prefix}{new_seq:04d}"


@transaction.atomic
def process_pos_checkout(
    *,
    company: Company,
    cashier=None,
    items_data: list,
    payment_method: str = "CASH",
    amount_tendered=None,
    reference: str = "",
    discount_amount=Decimal("0.00"),
    idempotency_key: str = "",
    customer_name: str = "",
    customer_phone: str = "",
    notes: str = "",
    held_cart_id=None,
) -> POSSale:
    """
    Authoritative server-side checkout process:
    1. Idempotency guard: checks if this checkout was already processed.
    2. Validates and locks each product record with select_for_update().
    3. Re-computes prices and totals server-side (never trusts client pricing).
    4. Automatically decrements inventory via record_stock_movement(movement_type="OUT").
    5. Saves POSSale, POSSaleItem(s), and POSPayment atomically.
    """
    # 1. Idempotency check
    if idempotency_key:
        existing_sale = (
            POSSale.objects.filter(
                company=company,
                idempotency_key=idempotency_key,
            )
            .prefetch_related("items", "payments")
            .first()
        )
        if existing_sale:
            return existing_sale

    if not items_data:
        raise ValidationError("Shopping cart is empty.")

    if payment_method not in POSPayment.Method.values:
        raise ValidationError(f"Invalid payment method: {payment_method}")

    # Convert and validate discount
    if not isinstance(discount_amount, Decimal):
        discount_amount = Decimal(str(discount_amount or 0))
    if discount_amount < 0:
        raise ValidationError("Discount cannot be negative.")

    pos_settings = get_pos_settings(company)

    # 2. Extract and lock products
    normalized_items = []

    for item in items_data:
        raw_id = item.get("id") or item.get("product_id")
        try:
            qty = int(item.get("quantity") or 0)
        except (ValueError, TypeError):
            raise ValidationError("Invalid item quantity.")

        if qty <= 0:
            raise ValidationError("Item quantity must be greater than zero.")

        try:
            prod_id = int(raw_id)
        except (ValueError, TypeError):
            prod_id = raw_id

        normalized_items.append({"id": prod_id, "raw_id": raw_id, "quantity": qty})

    raw_ids = [it["id"] for it in normalized_items]
    locked_products = {}
    for p in (
        Product.objects.select_for_update()
        .filter(pk__in=raw_ids, company=company, is_active=True)
    ):
        locked_products[p.pk] = p
        locked_products[str(p.pk)] = p

    calculated_items = []
    subtotal = Decimal("0.00")

    for it in normalized_items:
        prod_id = it["id"]
        raw_id = it["raw_id"]
        product = locked_products.get(prod_id) or locked_products.get(raw_id) or locked_products.get(str(prod_id))
        if not product:
            raise ValidationError(f"Product (ID {raw_id}) is inactive or not found.")

        qty = it["quantity"]
        unit_price = product.selling_price
        line_total = unit_price * qty
        subtotal += line_total

        calculated_items.append({
            "product": product,
            "quantity": qty,
            "unit_price": unit_price,
            "line_total": line_total,
        })

    # Validate discount against settings max_discount_percent
    if discount_amount > 0:
        max_allowed = (subtotal * pos_settings.max_discount_percent) / Decimal("100")
        if discount_amount > max_allowed:
            raise ValidationError(
                f"Discount exceeds maximum allowed of {pos_settings.max_discount_percent}% (₹{max_allowed:.2f})."
            )

    tax_amount = Decimal("0.00")
    grand_total = max(Decimal("0.00"), subtotal - discount_amount + tax_amount)

    # Validate tender amount
    if amount_tendered is not None:
        if not isinstance(amount_tendered, Decimal):
            amount_tendered = Decimal(str(amount_tendered))
    else:
        amount_tendered = grand_total

    if payment_method == POSPayment.Method.CASH:
        if amount_tendered < grand_total:
            raise ValidationError(
                f"Amount tendered (₹{amount_tendered:.2f}) is less than grand total (₹{grand_total:.2f})."
            )
        change_due = amount_tendered - grand_total
    else:
        amount_tendered = grand_total
        change_due = Decimal("0.00")

    # 3. Generate Sale Number
    sale_number = generate_sale_number(company)

    # 4. Inventory Stock OUT for each item
    for item in calculated_items:
        product = item["product"]
        qty = item["quantity"]
        record_stock_movement(
            company=company,
            product=product,
            movement_type=StockMovement.MovementType.STOCK_OUT,
            quantity=qty,
            reason=f"POS Sale {sale_number}",
        )

    # 5. Create POSSale
    sale = POSSale.objects.create(
        company=company,
        cashier=cashier,
        sale_number=sale_number,
        customer_name=customer_name.strip(),
        customer_phone=customer_phone.strip(),
        subtotal=subtotal,
        discount_amount=discount_amount,
        tax_amount=tax_amount,
        grand_total=grand_total,
        status=POSSale.Status.COMPLETED,
        idempotency_key=idempotency_key.strip(),
        notes=notes.strip(),
    )

    # 6. Create POSSaleItem records
    for item in calculated_items:
        POSSaleItem.objects.create(
            sale=sale,
            product=item["product"],
            product_name=item["product"].name,
            product_sku=item["product"].sku,
            quantity=item["quantity"],
            unit_price=item["unit_price"],
            discount_amount=Decimal("0.00"),
            tax_amount=Decimal("0.00"),
            line_total=item["line_total"],
        )

    # 7. Create POSPayment record
    POSPayment.objects.create(
        sale=sale,
        payment_method=payment_method,
        amount=grand_total,
        amount_tendered=amount_tendered,
        change_due=change_due,
        reference=reference.strip(),
        status=POSPayment.Status.CONFIRMED,
    )

    # 8. Clean up held cart if applicable
    if held_cart_id:
        POSHeldCart.objects.filter(pk=held_cart_id, company=company).delete()

    return sale


def save_held_cart(company: Company, cashier, hold_reference: str, customer_note: str, cart_data: list) -> POSHeldCart:
    """Save an in-progress cart on hold."""
    if not cart_data:
        raise ValidationError("Cannot hold an empty cart.")
    if not hold_reference:
        hold_reference = f"Hold-{timezone.now().strftime('%H%M%S')}"

    return POSHeldCart.objects.create(
        company=company,
        cashier=cashier,
        hold_reference=hold_reference.strip(),
        customer_note=customer_note.strip(),
        cart_data=cart_data,
    )


def recall_held_cart(company: Company, held_id: int):
    """Retrieve a held cart and remove it from held storage."""
    held_cart = POSHeldCart.objects.filter(pk=held_id, company=company).first()
    if not held_cart:
        raise ValidationError("Held cart not found or already recalled.")
    data = held_cart.cart_data
    reference = held_cart.hold_reference
    held_cart.delete()
    return data, reference

