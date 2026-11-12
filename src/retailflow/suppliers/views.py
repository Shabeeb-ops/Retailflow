from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from company.context import get_current_tenant
from company.models import Company
from .forms import SupplierForm, SupplierProductForm
from .models import Supplier, SupplierProduct


def owner_required(view):
    view = never_cache(view)

    @login_required
    @never_cache
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        company = get_current_tenant()
        if company is None or company.user_id != request.user.pk:
            raise PermissionDenied("Only the company owner can manage suppliers.")
        return view(request, *args, **kwargs)
    return wrapped


def links_for(company):
    return SupplierProduct.objects.filter(
        company=company, supplier__company=company, product__company=company,
    ).select_related("supplier", "product")


def page(request, template, **context):
    is_popup = request.GET.get("popup") == "1" or request.headers.get("x-rf-window") == "1"
    base_template = "layouts/popup_base.html" if is_popup else "layouts/admin_base.html"
    return render(request, "suppliers/" + template, {
        "company": get_current_tenant(),
        "active_nav": "suppliers",
        "is_popup": is_popup,
        "base_template": base_template,
        **context,
    })


@owner_required
@require_GET
def supplier_list(request):
    suppliers = Supplier.objects.filter(company=get_current_tenant())
    search = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if search:
        suppliers = suppliers.filter(Q(name__icontains=search) | Q(supplier_code__icontains=search) | Q(contact_person__icontains=search) | Q(phone__icontains=search) | Q(city__icontains=search) | Q(gstin__icontains=search))
    if status in ("active", "inactive"):
        suppliers = suppliers.filter(is_active=status == "active")
    return page(request, "list.html", page_obj=Paginator(suppliers, 25).get_page(request.GET.get("page")), search=search, selected_status=status)


@owner_required
@require_GET
def supplier_detail(request, pk):
    company = get_current_tenant()
    supplier = get_object_or_404(Supplier, company=company, pk=pk)
    fields = [(field.label, field.value()) for field in SupplierForm(instance=supplier, company=company)]
    return page(request, "detail.html", supplier=supplier, fields=fields, links=links_for(company).filter(supplier=supplier).order_by("product__name", "pk"))


def edit_record(request, model, form_class, pk, title):
    company = get_current_tenant()
    is_popup = request.GET.get("popup") == "1" or request.POST.get("popup") == "1" or request.headers.get("x-rf-window") == "1"
    # Serialize module writes per tenant, including case-insensitive code checks.
    with transaction.atomic():
        if request.method == "POST":
            Company.objects.select_for_update().get(pk=company.pk)
        queryset = Supplier.objects.filter(company=company) if model is Supplier else links_for(company)
        instance = get_object_or_404(queryset, pk=pk) if pk else None
        initial = {}
        if not instance and model is SupplierProduct and request.GET.get("supplier"):
            initial["supplier"] = request.GET.get("supplier")
        form = form_class(request.POST if request.method == "POST" else None, instance=instance, company=company, initial=initial)
        if request.method == "POST" and form.is_valid():
            try:
                with transaction.atomic():
                    saved = form.save()
            except (IntegrityError, ValidationError):
                form.add_error(None, "This record could not be saved. Check for duplicate codes, links or preferred suppliers and try again.")
            else:
                msg = title + " saved successfully."
                messages.success(request, msg)
                if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse({
                        "success": True,
                        "message": msg,
                        "pk": saved.pk,
                        "name": getattr(saved, "name", str(saved)),
                        "redirect_url": reverse("supplier_detail", args=[saved.pk]) if model is Supplier else reverse("supplier_product_list")
                    })
                return redirect("supplier_detail", pk=saved.pk) if model is Supplier else redirect("supplier_product_list")
    sections = []
    if model is Supplier:
        for heading, names in [
            ("Supplier information", "supplier_code name"),
            ("Contact information", "contact_person phone alternate_phone email"),
            ("Address", "address city state postal_code"),
            ("Business and tax information", "gstin payment_terms_days"),
            ("WhatsApp settings", "whatsapp_number whatsapp_opt_in auto_stock_alerts_enabled"),
            ("Status and notes", "is_active notes"),
        ]:
            sections.append((heading, [form[name] for name in names.split()]))
    else:
        sections = [("Product assignment", list(form))]
    return page(request, "form.html", form=form, sections=sections, title=("Edit " if pk else "Add ") + title, relationship=model is SupplierProduct)


@owner_required
@require_http_methods(["GET", "POST"])
def supplier_form(request, pk=None):
    return edit_record(request, Supplier, SupplierForm, pk, "Supplier")


@owner_required
@require_POST
def supplier_status(request, pk, active):
    company = get_current_tenant()
    with transaction.atomic():
        Company.objects.select_for_update().get(pk=company.pk)
        supplier = get_object_or_404(Supplier, company=company, pk=pk)
        supplier.is_active = active
        supplier.save(update_fields=["is_active", "updated_at"])
    msg = "Supplier activated." if active else "Supplier deactivated."
    messages.success(request, msg)
    if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.POST.get("popup") == "1":
        return JsonResponse({"success": True, "message": msg, "is_active": active, "pk": pk})
    return redirect("supplier_detail", pk=pk)


@owner_required
@require_GET
def supplier_product_list(request):
    links = links_for(get_current_tenant()).order_by("supplier__name", "product__name", "pk")
    return page(request, "products.html", page_obj=Paginator(links, 25).get_page(request.GET.get("page")))


@owner_required
@require_http_methods(["GET", "POST"])
def supplier_product_form(request, pk=None):
    return edit_record(request, SupplierProduct, SupplierProductForm, pk, "Supplier product")


@owner_required
@require_POST
def supplier_product_deactivate(request, pk):
    company = get_current_tenant()
    with transaction.atomic():
        Company.objects.select_for_update().get(pk=company.pk)
        link = get_object_or_404(links_for(company), pk=pk)
        links_for(company).filter(pk=link.pk).update(is_active=False, is_preferred=False)
    msg = "Relationship deactivated; its history has been preserved."
    messages.success(request, msg)
    if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.POST.get("popup") == "1":
        return JsonResponse({"success": True, "message": msg, "pk": pk})
    return redirect("supplier_product_list")
