
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse

from company.context import get_current_tenant

from .forms import StockMovementForm
from .models import Inventory
from .services import record_stock_movement


@login_required
def stock_movement_view(request):
    is_popup = request.GET.get("popup") == "1" or request.POST.get("popup") == "1" or request.headers.get("x-rf-window") == "1"
    base_template = "layouts/popup_base.html" if is_popup else "layouts/admin_base.html"

    # Step 1: Get the company from TenantMiddleware
    company = get_current_tenant()

    if company is None:
        if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "error": "No company is associated with your account."}, status=400)
        messages.error(
            request,
            "No company is associated with your account."
        )
        return redirect("product_list")

    # Step 2: Handle stock movement form submission
    if request.method == "POST":
        form = StockMovementForm(request.POST, company=company)

        if form.is_valid():
            try:
                inventory = record_stock_movement(
                    company=company,
                    product=form.cleaned_data["product"],
                    movement_type=form.cleaned_data["movement_type"],
                    quantity=form.cleaned_data["quantity"],
                    reason=form.cleaned_data["reason"],
                )

                msg = f"Stock updated successfully. Current quantity: {inventory.quantity}"
                messages.success(request, msg)

                if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse({
                        "success": True,
                        "message": msg,
                        "product_id": inventory.product_id,
                        "product_name": inventory.product.name,
                        "quantity": inventory.quantity,
                        "redirect_url": reverse("stock_movement")
                    })

                return redirect("stock_movement")

            except ValidationError as error:
                form.add_error(None, error.messages)

        if is_popup and request.headers.get("x-requested-with") == "XMLHttpRequest":
            template = "inventory/stock_movement_form.html" if is_popup else "inventory/stock_movement.html"
            return render(request, template, {
                "form": form,
                "is_popup": True,
                "base_template": base_template
            }, status=400)

    else:
        form = StockMovementForm(company=company)

    if is_popup:
        return render(
            request,
            "inventory/stock_movement_form.html",
            {
                "form": form,
                "is_popup": True,
                "base_template": base_template
            }
        )

    # Step 3: Fetch only the current company's inventory
    inventory_items = (
        Inventory.objects
        .filter(
            company=company,
            product__is_active=True
        )
        .select_related("product")
        .order_by("product__name")
    )

    # Step 4: Render the existing inventory page
    return render(
        request,
        "inventory/stock_movement.html",
        {
            "form": form,
            "inventory_items": inventory_items,
        },
    )
