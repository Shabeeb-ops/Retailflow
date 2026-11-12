import json
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, IntegerField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from company.context import get_current_tenant
from employees.permissions import role_required
from products.models import Category, Product
from .forms import POSSettingsForm
from .models import POSHeldCart, POSPayment, POSSale, POSSaleItem, POSSettings
from .services import (
    get_pos_settings,
    process_pos_checkout,
    recall_held_cart,
    save_held_cart,
)


def _get_active_company(request):
    """Retrieve company context for cashier or owner/manager."""
    if hasattr(request.user, "employee") and request.user.employee:
        return request.user.employee.company
    tenant = get_current_tenant()
    if tenant:
        return tenant
    if hasattr(request.user, "company"):
        return request.user.company
    return None


@login_required
def pos_terminal(request):
    """
    Touchscreen-friendly POS Terminal:
    - Company-scoped products with live stock annotation.
    - Barcode and SKU lookup.
    - Category tabs.
    - Dynamic cart management with hold/recall and thermal receipt checkout.
    """
    employee = getattr(request.user, "employee", None)
    if employee and employee.role not in ["CASHIER", "MANAGER"]:
        return HttpResponseForbidden("You do not have permission to access the POS Terminal.")

    company = _get_active_company(request)
    if not company:
        return redirect("company_registration")

    categories = Category.objects.filter(company=company, is_active=True).order_by("name")

    products = (
        Product.objects.filter(
            company=company,
            is_active=True,
        )
        .select_related("category")
        .annotate(
            available_stock=Coalesce(
                Sum("inventory_records__quantity"),
                Value(0),
                output_field=IntegerField(),
            )
        )
        .order_by("name")
    )

    settings = get_pos_settings(company)
    held_carts_count = POSHeldCart.objects.filter(company=company).count()

    return render(
        request,
        "pos/terminal.html",
        {
            "employee": employee,
            "company": company,
            "products": products,
            "categories": categories,
            "settings": settings,
            "held_carts_count": held_carts_count,
        },
    )


@login_required
@require_POST
def pos_checkout(request):
    """
    AJAX Checkout API:
    - Server-side authoritative validation
    - Inventory Stock OUT
    - Atomic sale and payment creation
    - Idempotency guard against double-checkout
    """
    company = _get_active_company(request)
    if not company:
        return JsonResponse({"success": False, "error": "Company not identified."}, status=400)

    cashier = getattr(request.user, "employee", None)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"success": False, "error": "Invalid JSON payload."}, status=400)

    items = data.get("items", [])
    payment_method = data.get("payment_method", "CASH")
    amount_tendered = data.get("amount_tendered")
    reference = data.get("reference", "")
    discount_amount = data.get("discount_amount", 0)
    idempotency_key = data.get("idempotency_key", "")
    customer_name = data.get("customer_name", "")
    customer_phone = data.get("customer_phone", "")
    notes = data.get("notes", "")
    held_cart_id = data.get("held_cart_id")

    try:
        sale = process_pos_checkout(
            company=company,
            cashier=cashier,
            items_data=items,
            payment_method=payment_method,
            amount_tendered=amount_tendered,
            reference=reference,
            discount_amount=discount_amount,
            idempotency_key=idempotency_key,
            customer_name=customer_name,
            customer_phone=customer_phone,
            notes=notes,
            held_cart_id=held_cart_id,
        )
    except ValidationError as exc:
        msg = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        return JsonResponse({"success": False, "error": msg}, status=400)
    except Exception as exc:
        return JsonResponse({"success": False, "error": f"Checkout failed: {str(exc)}"}, status=500)

    first_payment = sale.payments.first()
    change_due = first_payment.change_due if first_payment else Decimal("0.00")

    return JsonResponse({
        "success": True,
        "sale_id": sale.pk,
        "sale_number": sale.sale_number,
        "grand_total": str(sale.grand_total),
        "change_due": str(change_due),
        "receipt_url": reverse("pos_receipt", args=[sale.pk]),
        "print_url": reverse("pos_receipt_print", args=[sale.pk]),
    })


@login_required
@require_GET
def pos_receipt(request, sale_id):
    """Display receipt for thermal printing or viewing inside POS modal."""
    company = _get_active_company(request)
    sale = get_object_or_404(
        POSSale.objects.select_related("company", "cashier").prefetch_related("items", "payments"),
        pk=sale_id,
        company=company,
    )
    settings = get_pos_settings(company)
    return render(
        request,
        "pos/receipt.html",
        {
            "sale": sale,
            "company": company,
            "settings": settings,
            "payment": sale.payments.first(),
        },
    )


@login_required
@require_GET
def pos_receipt_print(request, sale_id):
    """Standalone thermal receipt view that triggers auto-print."""
    company = _get_active_company(request)
    sale = get_object_or_404(
        POSSale.objects.select_related("company", "cashier").prefetch_related("items", "payments"),
        pk=sale_id,
        company=company,
    )
    settings = get_pos_settings(company)
    return render(
        request,
        "pos/receipt_print.html",
        {
            "sale": sale,
            "company": company,
            "settings": settings,
            "payment": sale.payments.first(),
        },
    )


@login_required
@require_POST
def pos_hold_cart(request):
    """Hold an in-progress cart."""
    company = _get_active_company(request)
    cashier = getattr(request.user, "employee", None)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"success": False, "error": "Invalid JSON."}, status=400)

    cart_data = data.get("cart_data", [])
    hold_reference = data.get("hold_reference", "")
    customer_note = data.get("customer_note", "")

    try:
        held = save_held_cart(company, cashier, hold_reference, customer_note, cart_data)
        count = POSHeldCart.objects.filter(company=company).count()
        return JsonResponse({
            "success": True,
            "held_id": held.pk,
            "reference": held.hold_reference,
            "count": count,
        })
    except ValidationError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)


@login_required
@require_GET
def pos_list_held_carts(request):
    """List held carts for recall modal."""
    company = _get_active_company(request)
    carts = POSHeldCart.objects.filter(company=company).order_by("-created_at")

    results = []
    for c in carts:
        items_count = sum(item.get("quantity", 1) for item in c.cart_data) if isinstance(c.cart_data, list) else 0
        total_estimate = sum(
            float(item.get("price") or item.get("pricePaise", 0) / 100 or 0) * item.get("quantity", 1)
            for item in c.cart_data
        ) if isinstance(c.cart_data, list) else 0.0

        results.append({
            "id": c.pk,
            "reference": c.hold_reference,
            "customer_note": c.customer_note,
            "items_count": items_count,
            "total_estimate": f"{total_estimate:.2f}",
            "created_at": c.created_at.strftime("%I:%M %p"),
        })

    return JsonResponse({"success": True, "carts": results})


@login_required
@require_POST
def pos_recall_cart(request, held_id):
    """Recall a held cart, deleting it from held storage and returning cart data."""
    company = _get_active_company(request)
    try:
        cart_data, reference = recall_held_cart(company, held_id)
        count = POSHeldCart.objects.filter(company=company).count()
        return JsonResponse({
            "success": True,
            "cart_data": cart_data,
            "reference": reference,
            "count": count,
        })
    except ValidationError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)


@login_required
@require_POST
def pos_delete_held_cart(request, held_id):
    """Delete a held cart without recalling."""
    company = _get_active_company(request)
    deleted, _ = POSHeldCart.objects.filter(pk=held_id, company=company).delete()
    count = POSHeldCart.objects.filter(company=company).count()
    return JsonResponse({"success": True, "deleted": deleted > 0, "count": count})


@login_required
@require_GET
def pos_barcode_search(request, code):
    """Look up product by exact barcode or SKU."""
    company = _get_active_company(request)
    code = code.strip()

    product = (
        Product.objects.filter(
            Q(barcode__iexact=code) | Q(sku__iexact=code),
            company=company,
            is_active=True,
        )
        .annotate(
            available_stock=Coalesce(
                Sum("inventory_records__quantity"),
                Value(0),
                output_field=IntegerField(),
            )
        )
        .first()
    )

    if not product:
        return JsonResponse({"found": False, "message": "Product not found."})

    return JsonResponse({
        "found": True,
        "product": {
            "id": product.pk,
            "name": product.name,
            "sku": product.sku,
            "barcode": product.barcode,
            "price": str(product.selling_price),
            "stock": product.available_stock,
            "image_url": product.image.url if product.image else None,
        },
    })


@login_required
def pos_sales_history(request):
    """View completed sales with search and reprint options."""
    company = _get_active_company(request)
    sales = POSSale.objects.filter(company=company).select_related("cashier").prefetch_related("payments").order_by("-created_at")

    q = request.GET.get("q", "").strip()
    if q:
        sales = sales.filter(
            Q(sale_number__icontains=q)
            | Q(customer_name__icontains=q)
            | Q(customer_phone__icontains=q)
        )

    date_filter = request.GET.get("date", "")
    if date_filter:
        try:
            d = timezone.datetime.strptime(date_filter, "%Y-%m-%d").date()
            sales = sales.filter(created_at__date=d)
        except ValueError:
            pass

    paginator = Paginator(sales, 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "pos/sales_history.html",
        {
            "company": company,
            "page_obj": page_obj,
            "search_query": q,
            "date_filter": date_filter,
            "active_nav": "pos_history",
        },
    )


@login_required
def pos_sale_detail(request, sale_id):
    """Detailed view of an individual sale."""
    company = _get_active_company(request)
    sale = get_object_or_404(
        POSSale.objects.select_related("company", "cashier").prefetch_related("items", "payments"),
        pk=sale_id,
        company=company,
    )
    return render(
        request,
        "pos/sale_detail.html",
        {
            "company": company,
            "sale": sale,
            "items": sale.items.all(),
            "payments": sale.payments.all(),
            "active_nav": "pos_history",
        },
    )


@login_required
def pos_reports(request):
    """Daily and periodic sales reports."""
    company = _get_active_company(request)
    today = timezone.now().date()

    today_sales = POSSale.objects.filter(company=company, created_at__date=today, status=POSSale.Status.COMPLETED)
    today_total = today_sales.aggregate(total=Coalesce(Sum("grand_total"), Decimal("0.00")))["total"]
    today_count = today_sales.count()

    # Payment breakdown
    payments_today = (
        POSPayment.objects.filter(sale__company=company, sale__created_at__date=today)
        .values("payment_method")
        .annotate(total=Sum("amount"), count=Count("id"))
    )

    # Top selling products today
    top_items = (
        POSSaleItem.objects.filter(sale__company=company, sale__created_at__date=today)
        .values("product_name", "product_sku")
        .annotate(total_qty=Sum("quantity"), total_revenue=Sum("line_total"))
        .order_by("-total_qty")[:10]
    )

    return render(
        request,
        "pos/reports.html",
        {
            "company": company,
            "today": today,
            "today_total": today_total,
            "today_count": today_count,
            "payments_today": payments_today,
            "top_items": top_items,
            "active_nav": "pos_reports",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def pos_settings(request):
    """Manage company POS configuration and receipt branding."""
    if hasattr(request.user, "employee") and request.user.employee and request.user.employee.role == "CASHIER":
        messages.warning(request, "Cashiers cannot access POS Settings.")
        return redirect("pos_sales_history")

    company = _get_active_company(request)
    settings = get_pos_settings(company)

    if request.method == "POST":
        form = POSSettingsForm(request.POST, instance=settings)
        if form.is_valid():
            form.save()
            messages.success(request, "POS Settings updated successfully.")
            return redirect("pos_settings")
    else:
        form = POSSettingsForm(instance=settings)

    return render(
        request,
        "pos/settings.html",
        {
            "company": company,
            "form": form,
            "settings": settings,
            "active_nav": "pos_settings",
        },
    )
