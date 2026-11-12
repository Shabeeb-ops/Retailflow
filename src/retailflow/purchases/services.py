from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from company.models import Company
from suppliers.models import Supplier, SupplierProduct
from inventory.services import record_stock_movement
from .models import PurchaseOrder, PurchaseOrderItem, GoodsReceipt, GoodsReceiptItem, PurchaseInvoice, PurchaseInvoiceItem, PurchasePayment, money


def lock_company(company, user):
    if company is None or not user.is_authenticated or not user.is_active or company.user_id != user.pk:
        raise PermissionDenied("Only the company owner can manage purchases.")
    # All purchasing writes lock company first, then documents, then inventory.
    return Company.objects.select_for_update().get(pk=company.pk)


def next_number(model, company, prefix):
    """Caller holds the company lock. Preserve existing numbers, including gaps."""
    numbers = model.objects.filter(company=company, number__startswith=prefix + "-").values_list("number", flat=True)
    sequence = max((int(n[len(prefix) + 1:]) for n in numbers if n[len(prefix) + 1:].isdigit()), default=0) + 1
    return f"{prefix}-{sequence:04d}"


def validate_supplier_product(company, supplier, product):
    if supplier.company_id != company.pk or product.company_id != company.pk:
        raise ValidationError("Supplier and product must belong to your company.")
    if not supplier.is_active or not product.is_active:
        raise ValidationError("Choose an active supplier and product.")
    links = SupplierProduct.objects.filter(company=company, supplier=supplier)
    # Existing assignments define the supplier catalogue; unconfigured suppliers
    # can use any company product until their catalogue is established.
    if links.exists() and not links.filter(product=product, is_active=True).exists():
        raise ValidationError(f"{product.name} is not actively assigned to this supplier.")


@transaction.atomic
def save_order(*, company, user, data, lines, pk=None):
    lock_company(company, user)
    order = PurchaseOrder.objects.select_for_update().get(company=company, pk=pk) if pk else PurchaseOrder(company=company, created_by=user, number=next_number(PurchaseOrder, company, "PO"))
    if order.status != PurchaseOrder.Status.DRAFT:
        raise ValidationError("Only draft orders can be edited.")
    supplier = Supplier.objects.filter(company=company, pk=data["supplier"].pk).first()
    if supplier is None:
        raise ValidationError("Supplier must belong to your company.")
    if not lines:
        raise ValidationError("Add at least one product.")
    if len({line["product"].pk for line in lines}) != len(lines):
        raise ValidationError("Each product can appear only once.")
    for line in lines:
        validate_supplier_product(company, supplier, line["product"])
        quantity = line["quantity"]
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            raise ValidationError("Ordered quantities must be positive whole units.")
    for key in ("supplier", "order_date", "expected_delivery_date", "notes"):
        setattr(order, key, data[key])
    order.save()
    # Draft lines have no receiving/invoice history and can be replaced safely.
    order.items.all().delete()
    for line in lines:
        PurchaseOrderItem.objects.create(order=order, **{key: line[key] for key in ("product", "quantity", "unit_cost", "discount_percent", "tax_percent")})
    if order.totals["line_total"] > money("9999999999999999.99"):
        raise ValidationError("Order total exceeds the supported monetary limit.")
    return order


@transaction.atomic
def transition_order(*, company, user, pk, action):
    lock_company(company, user)
    order = PurchaseOrder.objects.select_for_update().get(company=company, pk=pk)
    if action == "place":
        if order.status != PurchaseOrder.Status.DRAFT or not order.items.exists():
            raise ValidationError("Only a draft with valid items can be placed.")
        for line in order.items.select_related("product"):
            validate_supplier_product(company, order.supplier, line.product)
            line.full_clean()
        order.status = PurchaseOrder.Status.ORDERED
    elif action == "cancel":
        if order.status not in (PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.ORDERED) or order.receipts.filter(status="CONFIRMED").exists():
            raise ValidationError("Received or cancelled orders cannot be cancelled.")
        order.status = PurchaseOrder.Status.CANCELLED
    else:
        raise ValidationError("Unknown order action.")
    order._workflow = True
    order.save()
    return order


def validate_receiving_order(order, company):
    if order.company_id != company.pk or order.supplier.company_id != company.pk:
        raise ValidationError("Order and supplier must belong to this company.")
    if order.status not in (PurchaseOrder.Status.ORDERED, PurchaseOrder.Status.PARTIALLY_RECEIVED):
        raise ValidationError("Only an outstanding placed order can receive goods.")


def validate_receipt_lines(order, lines):
    if not lines:
        raise ValidationError("Record at least one delivered quantity.")
    seen = set()
    for line in lines:
        item = line["order_item"]
        if item.pk in seen or item.order_id != order.pk or item.product.company_id != order.company_id:
            raise ValidationError("Each receipt line must reference a different item in this company's order.")
        seen.add(item.pk)
        quantities = [line[key] for key in ("accepted_quantity", "damaged_quantity", "rejected_quantity")]
        if any(not isinstance(q, int) or isinstance(q, bool) or q < 0 for q in quantities):
            raise ValidationError("Receipt quantities must be nonnegative whole units.")
        delivered = sum(quantities)
        if delivered <= 0 or delivered > item.remaining_quantity:
            raise ValidationError(f"{item.product_name}: delivered quantity must be between 1 and {item.remaining_quantity} outstanding units.")


@transaction.atomic
def save_receipt(*, company, user, order_pk, data, lines, pk=None):
    lock_company(company, user)
    order = PurchaseOrder.objects.select_for_update().get(company=company, pk=order_pk)
    validate_receiving_order(order, company)
    receipt = GoodsReceipt.objects.select_for_update().get(company=company, order=order, pk=pk) if pk else GoodsReceipt(company=company, order=order, received_by=user, number=next_number(GoodsReceipt, company, "GRN"))
    if receipt.status != GoodsReceipt.Status.DRAFT:
        raise ValidationError("Confirmed receipts cannot be edited.")
    validate_receipt_lines(order, lines)
    for key in ("receipt_date", "delivery_reference", "notes"):
        setattr(receipt, key, data[key])
    receipt.save()
    receipt.items.all().delete()
    for line in lines:
        GoodsReceiptItem.objects.create(receipt=receipt, **{key: line[key] for key in ("order_item", "accepted_quantity", "damaged_quantity", "rejected_quantity", "notes")})
    return receipt


@transaction.atomic
def confirm_receipt(*, company, user, pk):
    lock_company(company, user)
    receipt = GoodsReceipt.objects.select_for_update().get(company=company, pk=pk)
    if receipt.status == GoodsReceipt.Status.CONFIRMED:
        return receipt  # Idempotent retries never touch stock or invoices.
    order = PurchaseOrder.objects.select_for_update().get(company=company, pk=receipt.order_id)
    validate_receiving_order(order, company)
    lines = list(receipt.items.select_related("order_item__product").order_by("order_item__product_id"))
    validate_receipt_lines(order, [{key: getattr(line, key) for key in ("order_item", "accepted_quantity", "damaged_quantity", "rejected_quantity")} for line in lines])
    for line in lines:
        if line.accepted_quantity:
            record_stock_movement(company=company, product=line.order_item.product, movement_type="IN", quantity=line.accepted_quantity, reason=f"Goods received: {receipt.number} / {order.number}"[:100])
    receipt.status = GoodsReceipt.Status.CONFIRMED
    receipt.confirmed_by, receipt.confirmed_at = user, timezone.now()
    receipt._workflow = True
    receipt.save()
    items = list(order.items.all())
    if all(item.remaining_quantity == 0 for item in items):
        order.status = PurchaseOrder.Status.RECEIVED
    elif any(item.received_quantity for item in items):
        order.status = PurchaseOrder.Status.PARTIALLY_RECEIVED
    order._workflow = True
    order.save()
    create_receipt_invoice(receipt)
    return receipt


def create_receipt_invoice(receipt):
    """Called inside confirmation's transaction and company lock only."""
    lines = list(receipt.items.filter(accepted_quantity__gt=0).select_related("order_item__product"))
    if not lines:
        return None  # Returned-only deliveries have nothing billable.
    company, supplier = receipt.company, receipt.order.supplier
    invoice = PurchaseInvoice(
        company=company, supplier=supplier, order=receipt.order, receipt=receipt,
        number=next_number(PurchaseInvoice, company, "PINV"), invoice_date=receipt.receipt_date,
        currency=company.currency,
        company_snapshot={"name": company.company_name, "address": company.address, "state": company.state, "phone": company.phone, "email": company.email, "registration_number": company.company_registration_number},
        supplier_snapshot={"name": supplier.name, "code": supplier.supplier_code, "address": supplier.address, "city": supplier.city, "state": supplier.state, "phone": supplier.phone, "email": supplier.email, "gstin": supplier.gstin},
    )
    invoice.save()
    for line in lines:
        item = line.order_item
        previous = PurchaseInvoiceItem.objects.filter(invoice__company=company, receipt_item__order_item=item)
        previous_quantity = sum(previous.values_list("quantity", flat=True))
        # Cumulative allocation makes all partial invoices sum to the PO's
        # rounded discount/tax, including the final rounding penny.
        cumulative = previous_quantity + line.accepted_quantity
        discount = money(item.discount_amount * cumulative / item.quantity) - sum(previous.values_list("discount_amount", flat=True))
        tax = money(item.tax_amount * cumulative / item.quantity) - sum(previous.values_list("tax_amount", flat=True))
        subtotal = money(item.unit_cost * line.accepted_quantity)
        PurchaseInvoiceItem.objects.create(invoice=invoice, receipt_item=line, product=item.product, product_name=item.product_name, product_sku=item.product_sku, quantity=line.accepted_quantity, unit_cost=item.unit_cost, subtotal=subtotal, discount_amount=discount, tax_amount=tax, line_total=subtotal-discount+tax)
        invoice.subtotal += subtotal
        invoice.discounts += discount
        invoice.tax_amount += tax
    invoice.grand_total = invoice.subtotal - invoice.discounts + invoice.tax_amount
    invoice.clean_fields()
    invoice.validate_constraints()
    # Source totals are set only as part of initial generation, before exposure.
    PurchaseInvoice.objects.filter(pk=invoice.pk, company=company).update(subtotal=invoice.subtotal, discounts=invoice.discounts, tax_amount=invoice.tax_amount, grand_total=invoice.grand_total)
    return invoice


@transaction.atomic
def reconcile_invoice(*, company, user, pk, data):
    lock_company(company, user)
    invoice = PurchaseInvoice.objects.select_for_update().get(company=company, pk=pk)
    if invoice.status != PurchaseInvoice.Status.PENDING:
        raise ValidationError("This invoice is already verified and cannot be changed.")
    if not data.get("verified"):
        raise ValidationError("Confirm that the allocated amounts match the supplier bill.")
    for key in ("supplier_invoice_number", "invoice_date", "tax_amount", "additional_charges", "notes"):
        setattr(invoice, key, data[key])
    invoice.grand_total = money(invoice.subtotal - invoice.discounts + invoice.tax_amount + invoice.additional_charges)
    invoice.status = PurchaseInvoice.Status.VERIFIED
    invoice.verified_by, invoice.verified_at = user, timezone.now()
    invoice._workflow = True
    invoice.save()
    return invoice


@transaction.atomic
def record_payment(*, company, user, invoice_pk, data):
    lock_company(company, user)
    invoice = PurchaseInvoice.objects.select_for_update().get(company=company, pk=invoice_pk)
    if invoice.status != PurchaseInvoice.Status.VERIFIED:
        raise ValidationError("Verify the supplier bill before recording payments.")
    keys = ("payment_date", "amount", "method", "reference", "notes", "request_key")
    existing = invoice.payments.filter(request_key=data["request_key"]).first()
    if existing:
        if any(getattr(existing, key) != data[key] for key in keys):
            raise ValidationError("This payment request was already used with different details.")
        return existing
    if invoice.outstanding <= 0:
        raise ValidationError("This invoice is already fully paid.")
    if data.get("amount") is not None and data["amount"] > invoice.outstanding:
        raise ValidationError({"amount": "Payment exceeds the outstanding balance."})
    payment = PurchasePayment(invoice=invoice, recorded_by=user, **{key: data[key] for key in keys})
    payment.save()
    return payment
