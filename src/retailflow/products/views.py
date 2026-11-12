import csv
import io
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST, require_http_methods

from openpyxl import load_workbook

from .forms import CategoryForm, ProductForm
from .models import Category, Product
from company.context import get_current_tenant


def get_company(request):
    return get_current_tenant()



@login_required
def add_category(request):
    company = get_company(request)
    is_popup = request.GET.get("popup") == "1" or request.POST.get("popup") == "1" or request.headers.get("x-rf-window") == "1"

    if company is None:
        messages.error(request, "Please register your company first.")
        if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "message": "Please register your company first."})
        return redirect("product_list")

    if request.method == "POST":
        form = CategoryForm(request.POST)

        if form.is_valid():
            category = form.save(commit=False)
            category.company = company
            category.save()
            msg = f"Category '{category.name}' created successfully."
            messages.success(request, msg)
            if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({
                    "success": True,
                    "message": msg,
                    "pk": category.pk,
                    "name": category.name,
                    "redirect_url": reverse("product_list")
                })
            return redirect("product_list")
    else:
        form = CategoryForm()

    base_template = "layouts/popup_base.html" if is_popup else "layouts/admin_base.html"
    return render(
        request,
        "products/add_category.html",
        {
            "form": form,
            "is_popup": is_popup,
            "base_template": base_template
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def edit_category(request, pk):
    company = get_company(request)
    is_popup = request.GET.get("popup") == "1" or request.POST.get("popup") == "1" or request.headers.get("x-rf-window") == "1"

    if company is None:
        messages.error(request, "Please register your company first.")
        if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "message": "Please register your company first."})
        return redirect("product_list")

    category = get_object_or_404(Category, pk=pk, company=company)

    if request.method == "POST":
        form = CategoryForm(request.POST, instance=category)
        if form.is_valid():
            category = form.save()
            msg = f"Category '{category.name}' updated successfully."
            messages.success(request, msg)
            if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({
                    "success": True,
                    "message": msg,
                    "pk": category.pk,
                    "name": category.name,
                    "redirect_url": reverse("product_list")
                })
            return redirect("product_list")
    else:
        form = CategoryForm(instance=category)

    base_template = "layouts/popup_base.html" if is_popup else "layouts/admin_base.html"
    return render(
        request,
        "products/add_category.html",
        {
            "form": form,
            "category": category,
            "editing": True,
            "is_popup": is_popup,
            "base_template": base_template
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def add_product(request):
    company = get_company(request)
    is_popup = request.GET.get("popup") == "1" or request.POST.get("popup") == "1" or request.headers.get("x-rf-window") == "1"

    if company is None:
        messages.error(request, "Please register your company first.")
        if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "message": "Please register your company first."})
        return redirect("product_list")

    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES, company=company)
        if form.is_valid():
            product = form.save(commit=False)
            product.company = company
            product.save()
            msg = f"Product '{product.name}' created successfully."
            messages.success(request, msg)
            if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({
                    "success": True,
                    "message": msg,
                    "pk": product.pk,
                    "name": product.name,
                    "redirect_url": reverse("product_list")
                })
            return redirect("product_list")
    else:
        form = ProductForm(company=company)

    base_template = "layouts/popup_base.html" if is_popup else "layouts/admin_base.html"
    return render(
        request,
        "products/product_form.html",
        {
            "form": form,
            "title": "Add Product",
            "is_popup": is_popup,
            "base_template": base_template,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def edit_product(request, pk):
    company = get_company(request)
    is_popup = request.GET.get("popup") == "1" or request.POST.get("popup") == "1" or request.headers.get("x-rf-window") == "1"

    if company is None:
        messages.error(request, "Please register your company first.")
        if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "message": "Please register your company first."})
        return redirect("product_list")

    product = get_object_or_404(Product, pk=pk, company=company)

    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES, instance=product, company=company)
        if form.is_valid():
            product = form.save()
            msg = f"Product '{product.name}' updated successfully."
            messages.success(request, msg)
            if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({
                    "success": True,
                    "message": msg,
                    "pk": product.pk,
                    "name": product.name,
                    "redirect_url": reverse("product_list")
                })
            return redirect("product_list")
    else:
        form = ProductForm(instance=product, company=company)

    base_template = "layouts/popup_base.html" if is_popup else "layouts/admin_base.html"
    return render(
        request,
        "products/product_form.html",
        {
            "form": form,
            "product": product,
            "title": f"Edit Product — {product.name}",
            "editing": True,
            "is_popup": is_popup,
            "base_template": base_template,
        },
    )


@login_required
def product_list(request):
    company = get_company(request)

    if company is None:
        return render(
            request,
            "products/product_list.html",
            {"company_missing": True},
        )

    products = (
        Product.objects
        .filter(company=company)
        .select_related("category")
        .annotate(
            available_stock=Sum("inventory_records__quantity")
        )
    )

    # Search by product name or SKU.
    search = request.GET.get("q", "").strip()

    if search:
        products = products.filter(
            Q(name__icontains=search)
            | Q(sku__icontains=search)
        )

    # Filter by category.
    category_id = request.GET.get("category", "")

    if category_id.isdigit():
        products = products.filter(
            category_id=category_id,
            category__company=company,
        )

    # Filter by active status.
    status = request.GET.get("status", "")

    if status == "active":
        products = products.filter(is_active=True)
    elif status == "inactive":
        products = products.filter(is_active=False)

    # Give products a consistent order before pagination
    products = products.order_by("name", "pk")

    paginator = Paginator(products, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    categories = Category.objects.filter(
        company=company,
        is_active=True,
    )

    return render(
        request,
        "products/product_list.html",
        {
            "products": page_obj,
            "page_obj": page_obj,
            "categories": categories,
            "search": search,
            "selected_category": category_id,
            "selected_status": status,
        },
    )


@login_required
@require_POST
def inline_save(request):
    """Save multiple new product rows from the Products table."""
    company = get_company(request)

    if company is None:
        return JsonResponse(
            {"success": False, "message": "Register your company first."},
            status=400,
        )

    try:
        payload = json.loads(request.body)
        rows = payload.get("products", [])
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse(
            {"success": False, "message": "Invalid request data."},
            status=400,
        )

    if not isinstance(rows, list) or not rows:
        return JsonResponse(
            {"success": False, "message": "Add at least one product row."},
            status=400,
        )

    if len(rows) > 100:
        return JsonResponse(
            {"success": False, "message": "Save at most 100 rows at a time."},
            status=400,
        )

    forms = []
    errors = []
    submitted_skus = set()

    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            errors.append({"row": index, "errors": {"row": ["Invalid row."]}})
            continue

        form = ProductForm(row, company=company)
        row_errors = {}

        if not form.is_valid():
            row_errors = form.errors.get_json_data()

        sku = str(row.get("sku", "")).strip()

        if sku:
            normalized_sku = sku.casefold()

            if normalized_sku in submitted_skus:
                row_errors["sku"] = [
                    {"message": "This SKU is repeated in the submitted rows."}
                ]

            submitted_skus.add(normalized_sku)

            if Product.objects.filter(
                company=company,
                sku=sku,
            ).exists():
                row_errors["sku"] = [
                    {"message": "This SKU already exists for your company."}
                ]

        if row_errors:
            errors.append({"row": index, "errors": row_errors})

        forms.append(form)

    if errors:
        return JsonResponse(
            {
                "success": False,
                "message": "Correct the highlighted rows and try again.",
                "errors": errors,
            },
            status=400,
        )

    try:
        with transaction.atomic():
            for form in forms:
                product = form.save(commit=False)
                product.company = company
                product.save()
    except Exception:
        return JsonResponse(
            {
                "success": False,
                "message": (
                    "The products could not be saved. "
                    "Check the data and try again."
                ),
            },
            status=400,
        )

    return JsonResponse(
        {
            "success": True,
            "message": f"{len(forms)} product(s) saved successfully.",
        }
    )


def read_import_file(upload):
    """Return rows as dictionaries using the first row as column headers."""
    filename = upload.name.lower()

    if filename.endswith(".csv"):
        content = upload.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(content))
        return list(reader)

    if filename.endswith(".xlsx"):
        workbook = load_workbook(upload, read_only=True, data_only=True)
        sheet = workbook.active
        values = sheet.iter_rows(values_only=True)

        headers = next(values, None)

        if not headers:
            return []

        headers = [
            str(value).strip().lower() if value is not None else ""
            for value in headers
        ]

        rows = []

        for values_row in values:
            rows.append(dict(zip(headers, values_row)))

        workbook.close()
        return rows

    raise ValueError("Upload an .xlsx or .csv file.")


def normalize_import_row(row, company):
    """Convert a spreadsheet row into data accepted by ProductForm."""
    row = {
        str(key).strip().lower(): value
        for key, value in row.items()
        if key is not None
    }

    category_name = str(row.get("category") or "").strip()

    category = Category.objects.filter(
        company=company,
        name__iexact=category_name,
        is_active=True,
    ).first()

    if category is None:
        raise ValueError(
            f"Category '{category_name}' was not found among your active categories."
        )

    active_value = str(row.get("is_active", "true")).strip().lower()

    if active_value in ("true", "1", "yes", "active"):
        is_active = True
    elif active_value in ("false", "0", "no", "inactive"):
        is_active = False
    else:
        raise ValueError("is_active must be true or false.")

    return {
        "name": str(row.get("name") or "").strip(),
        "sku": str(row.get("sku") or "").strip(),
        "category": str(category.pk),
        "brand": str(row.get("brand") or "").strip(),
        "purchase_price": row.get("purchase_price"),
        "selling_price": row.get("selling_price"),
        "unit": str(row.get("unit") or "Piece").strip(),
        "low_stock_threshold": row.get("low_stock_threshold") or 10,
        "description": str(row.get("description") or "").strip(),
        "is_active": is_active,
    }


@login_required
def import_products(request):
    company = get_company(request)

    if company is None:
        messages.error(request, "Please register your company first.")
        return redirect("product_list")

    if request.method == "GET":
        return render(request, "products/import_preview.html")

    action = request.POST.get("action")

    # Step A: read the file and show a preview before importing.
    if action == "preview":
        upload = request.FILES.get("file")

        if not upload:
            messages.error(request, "Choose an Excel or CSV file.")
            return redirect("import_products")

        if upload.size > 5 * 1024 * 1024:
            messages.error(request, "The file must be 5 MB or smaller.")
            return redirect("import_products")

        try:
            raw_rows = read_import_file(upload)
        except (ValueError, UnicodeDecodeError, csv.Error) as exc:
            messages.error(request, str(exc))
            return redirect("import_products")

        if not raw_rows:
            messages.error(request, "The file contains no product rows.")
            return redirect("import_products")

        if len(raw_rows) > 2000:
            messages.error(request, "Import at most 2,000 rows at a time.")
            return redirect("import_products")

        preview_rows = []
        valid_rows = []
        seen_skus = set()

        for index, raw_row in enumerate(raw_rows, start=2):
            try:
                data = normalize_import_row(raw_row, company)
                form = ProductForm(data, company=company)

                if not form.is_valid():
                    raise ValueError(
                        "; ".join(
                            f"{field}: {', '.join(errors)}"
                            for field, errors in form.errors.items()
                        )
                    )

                sku = data["sku"].casefold()

                if sku in seen_skus:
                    raise ValueError("Duplicate SKU in this file.")

                seen_skus.add(sku)

                if Product.objects.filter(
                    company=company,
                    sku=data["sku"],
                ).exists():
                    raise ValueError("SKU already exists in your company.")

                valid_rows.append(data)
                preview_rows.append(
                    {"row_number": index, "data": data, "error": ""}
                )

            except (ValueError, TypeError) as exc:
                preview_rows.append(
                    {
                        "row_number": index,
                        "data": raw_row,
                        "error": str(exc),
                    }
                )

        request.session["product_import_rows"] = valid_rows

        return render(
            request,
            "products/import_preview.html",
            {
                "preview_rows": preview_rows,
                "valid_count": len(valid_rows),
                "error_count": len(preview_rows) - len(valid_rows),
                "preview_done": True,
            },
        )

    # Step B: save the validated rows only after user confirmation.
    if action == "confirm":
        rows = request.session.get("product_import_rows", [])

        if not rows:
            messages.error(request, "No validated rows are waiting to import.")
            return redirect("import_products")

        try:
            with transaction.atomic():
                for data in rows:
                    form = ProductForm(data, company=company)

                    if not form.is_valid():
                        raise ValueError("A product row is no longer valid.")

                    sku = data["sku"]

                    if Product.objects.filter(
                        company=company,
                        sku=sku,
                    ).exists():
                        raise ValueError(
                            f"SKU '{sku}' already exists. Review the file again."
                        )

                    product = form.save(commit=False)
                    product.company = company
                    product.save()

        except (ValueError, Exception) as exc:
            messages.error(request, f"Import failed: {exc}")
            return redirect("import_products")

        imported_count = len(rows)
        del request.session["product_import_rows"]

        messages.success(
            request,
            f"{imported_count} product(s) imported successfully.",
        )
        return redirect("product_list")

    messages.error(request, "Unknown import action.")
    return redirect("import_products")