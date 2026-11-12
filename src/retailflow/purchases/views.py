from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from company.context import get_current_tenant
from .forms import PurchaseOrderForm, OrderItemFormSet, GoodsReceiptForm, ReceiptItemFormSet, InvoiceReconciliationForm, PurchasePaymentForm
from .models import PurchaseOrder, GoodsReceipt, PurchaseInvoice, PurchasePayment
from . import services


def owner_required(view):
    view = never_cache(view)

    @login_required
    @never_cache
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        company = get_current_tenant()
        if company is None or company.user_id != request.user.pk:
            raise PermissionDenied("Only the company owner can manage purchases.")
        return view(request, *args, **kwargs)
    return wrapped


def page(request, template, **context):
    is_popup = request.GET.get("popup") == "1" or request.POST.get("popup") == "1" or request.headers.get("x-rf-window") == "1"
    base_template = "layouts/popup_base.html" if is_popup else "layouts/admin_base.html"
    return render(request, "purchases/" + template, {
        "company": get_current_tenant(),
        "active_nav": "purchases",
        "is_popup": is_popup,
        "base_template": base_template,
        **context
    })


def scoped(model):
    return model.objects.filter(company=get_current_tenant())


@owner_required
@require_GET
def order_list(request):
    orders = scoped(PurchaseOrder).select_related("supplier").prefetch_related("items")
    search, status = request.GET.get("q", "").strip(), request.GET.get("status", "")
    if search:
        orders = orders.filter(Q(number__icontains=search) | Q(supplier__name__icontains=search))
    if status in PurchaseOrder.Status.values:
        orders = orders.filter(status=status)
    for key, lookup in [("from", "order_date__gte"), ("to", "order_date__lte")]:
        try:
            date = parse_date(request.GET.get(key, ""))
        except ValueError:
            date = None
        if date:
            orders = orders.filter(**{lookup: date})
    query = request.GET.copy()
    query.pop("page", None)
    return page(request, "order_list.html", page_obj=Paginator(orders, 25).get_page(request.GET.get("page")), search=search, selected_status=status, statuses=PurchaseOrder.Status.choices, query=query.urlencode())


@owner_required
@require_http_methods(["GET", "POST"])
def order_form(request, pk=None):
    company = get_current_tenant()
    is_popup = request.GET.get("popup") == "1" or request.POST.get("popup") == "1" or request.headers.get("x-rf-window") == "1"
    order = get_object_or_404(scoped(PurchaseOrder), pk=pk) if pk else None
    if order and order.status != PurchaseOrder.Status.DRAFT:
        if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "error": "Only draft orders can be edited.", "redirect_url": reverse("purchase_order_detail", args=[pk])})
        messages.error(request, "Only draft orders can be edited.")
        return redirect("purchase_order_detail", pk=pk)
    data = request.POST if request.method == "POST" else None
    form = PurchaseOrderForm(data, instance=order, company=company)
    initial = list(order.items.values("product", "quantity", "unit_cost", "discount_percent", "tax_percent")) if order else []
    formset = OrderItemFormSet(data, initial=initial, prefix="items", form_kwargs={"company": company})
    if request.method == "POST":
        valid, items_valid = form.is_valid(), formset.is_valid()
        if valid and items_valid:
            try:
                lines = [f.cleaned_data for f in formset if f.cleaned_data and not f.cleaned_data.get("DELETE")]
                saved = services.save_order(company=company, user=request.user, pk=pk, data=form.cleaned_data, lines=lines)
                if request.POST.get("action") == "save_and_place":
                    saved = services.transition_order(company=company, user=request.user, pk=saved.pk, action="place")
            except ValidationError as error:
                form.add_error(None, error.messages)
            else:
                msg = "Purchase order saved and placed." if request.POST.get("action") == "save_and_place" else "Draft purchase order saved."
                messages.success(request, msg)
                if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse({
                        "success": True,
                        "message": msg,
                        "pk": saved.pk,
                        "order_number": saved.number,
                        "status": saved.status,
                        "redirect_url": reverse("purchase_order_detail", args=[saved.pk])
                    })
                return redirect("purchase_order_detail", pk=saved.pk)
    return page(request, "form.html", form=form, formset=formset, title="Edit purchase order" if pk else "Create purchase order", dynamic_items=True)


@owner_required
@require_GET
def order_detail(request, pk):
    order = get_object_or_404(scoped(PurchaseOrder).select_related("supplier").prefetch_related("items"), pk=pk)
    return page(request, "order_detail.html", order=order)


@owner_required
@require_POST
def order_action(request, pk, action):
    is_popup = request.GET.get("popup") == "1" or request.POST.get("popup") == "1" or request.headers.get("x-rf-window") == "1"
    order = get_object_or_404(scoped(PurchaseOrder), pk=pk)
    if action == "place" and order.status != PurchaseOrder.Status.DRAFT:
        if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "error": "This purchase order is already placed."})
        messages.error(request, "This purchase order is already placed.")
        return redirect("purchase_order_detail", pk=pk)
    try:
        services.transition_order(company=get_current_tenant(), user=request.user, pk=pk, action=action)
    except ValidationError as error:
        err_msg = " ".join(error.messages)
        if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "error": err_msg})
        messages.error(request, err_msg)
    else:
        msg = "Purchase order updated."
        messages.success(request, msg)
        if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({
                "success": True,
                "message": msg,
                "status": order.status,
                "redirect_url": reverse("purchase_order_detail", args=[pk])
            })
    return redirect("purchase_order_detail", pk=pk)


@owner_required
@require_GET
def receipt_list(request):
    receipts = scoped(GoodsReceipt).select_related("order")
    return page(request, "receipt_list.html", page_obj=Paginator(receipts, 25).get_page(request.GET.get("page")))


@owner_required
@require_http_methods(["GET", "POST"])
def receipt_form(request, order_pk, pk=None):
    is_popup = request.GET.get("popup") == "1" or request.POST.get("popup") == "1" or request.headers.get("x-rf-window") == "1"
    order = get_object_or_404(scoped(PurchaseOrder), pk=order_pk)
    receipt = get_object_or_404(scoped(GoodsReceipt), pk=pk, order=order) if pk else None
    if receipt and receipt.status != GoodsReceipt.Status.DRAFT:
        if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "error": "Confirmed receipts cannot be edited.", "redirect_url": reverse("goods_receipt_detail", args=[receipt.pk])})
        messages.error(request, "Confirmed receipts cannot be edited.")
        return redirect("goods_receipt_detail", pk=receipt.pk)
    if order.status not in (PurchaseOrder.Status.ORDERED, PurchaseOrder.Status.PARTIALLY_RECEIVED):
        if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "error": "This order cannot receive goods.", "redirect_url": reverse("purchase_order_detail", args=[order.pk])})
        messages.error(request, "This order cannot receive goods.")
        return redirect("purchase_order_detail", pk=order.pk)
    data = request.POST if request.method == "POST" else None
    form = GoodsReceiptForm(data, instance=receipt)
    initial = list(receipt.items.values("order_item", "accepted_quantity", "damaged_quantity", "rejected_quantity", "notes")) if receipt else [{"order_item": item.pk, "accepted_quantity": 0, "damaged_quantity": 0, "rejected_quantity": 0} for item in order.items.all() if item.remaining_quantity > 0]
    formset = ReceiptItemFormSet(data, initial=initial, prefix="items", form_kwargs={"order": order})
    if request.method == "POST":
        valid, items_valid = form.is_valid(), formset.is_valid()
        if valid and items_valid:
            lines = [f.cleaned_data for f in formset if f.cleaned_data and any(f.cleaned_data[key] for key in ("accepted_quantity", "damaged_quantity", "rejected_quantity"))]
            try:
                saved = services.save_receipt(company=get_current_tenant(), user=request.user, order_pk=order.pk, pk=pk, data=form.cleaned_data, lines=lines)
                if request.POST.get("action") == "confirm":
                    services.confirm_receipt(company=get_current_tenant(), user=request.user, pk=saved.pk)
            except ValidationError as error:
                form.add_error(None, error.messages)
            else:
                msg = "Goods receipt confirmed." if request.POST.get("action") == "confirm" else "Draft receipt saved. Stock changes only after confirmation."
                messages.success(request, msg)
                if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse({
                        "success": True,
                        "message": msg,
                        "pk": saved.pk,
                        "receipt_number": saved.number,
                        "order_pk": order.pk,
                        "confirmed": request.POST.get("action") == "confirm",
                        "redirect_url": reverse("goods_receipt_detail", args=[saved.pk])
                    })
                return redirect("goods_receipt_detail", pk=saved.pk)
    return page(request, "form.html", form=form, formset=formset, title=f"Receive goods — {order.number}", explanation="Enter this delivery only. Damaged and rejected units are returned to the supplier, not stocked or billed; replacement units remain outstanding.")


@owner_required
@require_GET
def receipt_detail(request, pk):
    receipt = get_object_or_404(scoped(GoodsReceipt).select_related("order"), pk=pk)
    return page(request, "receipt_detail.html", receipt=receipt)


@owner_required
@require_POST
def receipt_confirm(request, pk):
    is_popup = request.GET.get("popup") == "1" or request.POST.get("popup") == "1" or request.headers.get("x-rf-window") == "1"
    receipt = get_object_or_404(scoped(GoodsReceipt), pk=pk)
    if receipt.status == GoodsReceipt.Status.CONFIRMED:
        if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "error": "This goods receipt is already confirmed."})
        messages.info(request, "This goods receipt is already confirmed.")
        return redirect("goods_receipt_detail", pk=pk)
    try:
        services.confirm_receipt(company=get_current_tenant(), user=request.user, pk=pk)
    except ValidationError as error:
        err_msg = " ".join(error.messages)
        if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "error": err_msg})
        messages.error(request, err_msg)
    else:
        messages.success(request, "Goods receipt confirmed.")
        if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({
                "success": True,
                "message": "Goods receipt confirmed.",
                "pk": pk,
                "redirect_url": reverse("goods_receipt_detail", args=[pk])
            })
    return redirect("goods_receipt_detail", pk=pk)


@owner_required
@require_GET
def invoice_list(request):
    invoices = scoped(PurchaseInvoice).select_related("supplier", "order", "receipt")
    return page(request, "invoice_list.html", page_obj=Paginator(invoices, 25).get_page(request.GET.get("page")))


@owner_required
@require_GET
def invoice_detail(request, pk):
    invoice = get_object_or_404(scoped(PurchaseInvoice).select_related("order", "receipt").prefetch_related("items"), pk=pk)
    return page(request, "invoice_detail.html", invoice=invoice)


@owner_required
@require_http_methods(["GET", "POST"])
def invoice_reconcile(request, pk):
    is_popup = request.GET.get("popup") == "1" or request.POST.get("popup") == "1" or request.headers.get("x-rf-window") == "1"
    invoice = get_object_or_404(scoped(PurchaseInvoice), pk=pk)
    if invoice.status != PurchaseInvoice.Status.PENDING:
        if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "error": "This invoice is already verified and cannot be changed.", "redirect_url": reverse("purchase_invoice_detail", args=[pk])})
        messages.error(request, "This invoice is already verified and cannot be changed.")
        return redirect("purchase_invoice_detail", pk=pk)
    form = InvoiceReconciliationForm(request.POST if request.method == "POST" else None, instance=invoice)
    if request.method == "POST" and form.is_valid():
        try:
            services.reconcile_invoice(company=get_current_tenant(), user=request.user, pk=pk, data=form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, error.messages)
        else:
            messages.success(request, "Supplier bill verified. Invoice amounts are now locked.")
            if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({
                    "success": True,
                    "message": "Supplier bill verified. Invoice amounts are now locked.",
                    "pk": pk,
                    "redirect_url": reverse("purchase_invoice_detail", args=[pk])
                })
            return redirect("purchase_invoice_detail", pk=pk)
    return page(request, "form.html", form=form, title=f"Verify supplier bill — {invoice.number}", submit_label="Verify and lock invoice", explanation="Enter the real supplier bill reference and only the tax/charges allocated to this receipt. When a bill covers several GRNs, do not repeat the entire bill amount on each. Product costs and discounts retain the placed order values; resolve any cost discrepancy before verifying.")


@owner_required
@require_http_methods(["GET", "POST"])
def payment_form(request, pk):
    is_popup = request.GET.get("popup") == "1" or request.POST.get("popup") == "1" or request.headers.get("x-rf-window") == "1"
    invoice = get_object_or_404(scoped(PurchaseInvoice), pk=pk)
    if invoice.status != PurchaseInvoice.Status.VERIFIED:
        if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "error": "Verify the supplier bill before recording payments.", "redirect_url": reverse("purchase_invoice_detail", args=[pk])})
        messages.error(request, "Verify the supplier bill before recording payments.")
        return redirect("purchase_invoice_detail", pk=pk)
    if invoice.outstanding <= 0:
        if request.method == "POST":
            request_key = request.POST.get("request_key")
            if request_key and invoice.payments.filter(request_key=request_key).exists():
                msg = f"Payment completed successfully for {invoice.order.number}. The purchase is fully paid."
                messages.success(request, msg)
                if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse({
                        "success": True,
                        "message": msg,
                        "outstanding": 0,
                        "po_number": invoice.order.number,
                        "redirect_url": reverse("purchase_order_list")
                    })
                return redirect("purchase_order_list")
        msg = f"Invoice {invoice.number} is already fully paid."
        if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "error": msg, "redirect_url": reverse("purchase_invoice_detail", args=[pk])})
        messages.info(request, msg)
        return redirect("purchase_invoice_detail", pk=pk)
    form = PurchasePaymentForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            services.record_payment(company=get_current_tenant(), user=request.user, invoice_pk=pk, data=form.cleaned_data)
        except ValidationError as error:
            if hasattr(error, "message_dict"):
                for field, errors in error.message_dict.items():
                    form.add_error(field if field in form.fields else None, errors)
            else:
                form.add_error(None, error.messages)
        else:
            invoice.refresh_from_db()
            outstanding = invoice.outstanding
            if outstanding == 0:
                msg = f"Payment completed successfully for {invoice.order.number}. The purchase is fully paid."
                messages.success(request, msg)
                if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse({
                        "success": True,
                        "message": msg,
                        "outstanding": 0,
                        "po_number": invoice.order.number,
                        "redirect_url": reverse("purchase_order_list")
                    })
                return redirect("purchase_order_list")
            msg = f"Payment recorded. A balance of {invoice.currency} {outstanding:.2f} remains."
            messages.success(request, msg)
            if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({
                    "success": True,
                    "message": msg,
                    "outstanding": float(outstanding),
                    "currency": invoice.currency,
                    "redirect_url": reverse("purchase_invoice_detail", args=[pk])
                })
            return redirect("purchase_invoice_detail", pk=pk)
    return page(request, "form.html", form=form, title=f"Record payment — {invoice.number}", submit_label="Record payment", explanation=f"Outstanding: {invoice.currency} {invoice.outstanding}. This records a payment already made; it does not transfer money.")


@owner_required
@require_GET
def payment_list(request):
    payments = PurchasePayment.objects.filter(invoice__company=get_current_tenant()).select_related("invoice", "recorded_by")
    return page(request, "payment_list.html", page_obj=Paginator(payments, 25).get_page(request.GET.get("page")))
